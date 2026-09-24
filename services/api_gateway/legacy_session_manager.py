"""The str-keyed legacy session path, kept behind a compatibility adapter (#228).

No running gateway reaches it: every app builds a `TenantSessionManager`. It
stays until the cutover decision the OpenSpec design records, and only the
unregistered services/api_gateway/session.py and tests construct it.
tests/test_gateway_dependency_ownership.py fails if another gateway module
imports it.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from .quality_telemetry import SessionLifecyclePhase, SessionTerminationReason
from .session_manager import (
    ClientType,
    Session,
    SessionManagerBase,
    SessionMessage,
    SessionStatus,
    utc_now,
)
from .session_pseudonym import SessionPseudonymizer

try:  # Optional dependency for persistence
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis optional for tests
    Redis = None  # type: ignore

    class RedisError(Exception):  # type: ignore
        pass


_TENANT_STORE_UNAVAILABLE = "tenant session store is unavailable"


class LegacySessionManager(SessionManagerBase[str]):
    """Sessions under bare ids, with their own optional Redis persistence."""

    def __init__(
        self,
        *,
        pseudonymizer: Optional[SessionPseudonymizer] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(clock=clock, pseudonymizer=pseudonymizer)
        self.redis_client: Optional[Redis] = None
        self.redis_namespace: str = os.getenv("REDIS_NAMESPACE", "ssf")
        self.redis_enabled: bool = False
        self.websocket_connections: Dict[str, Dict[str, Any]] = {}
        self.active_admin_sessions: Set[str] = set()

        self.reset()
        self._init_persistence()

    def reset(self, *, clear_persistence: bool = False) -> None:
        """SessionManager Zustand auf Initialwerte zurücksetzen."""
        self.sessions = {}
        self.websocket_connections = {}
        self.active_admin_sessions = set()
        self.websocket_manager = None

        if clear_persistence and self.redis_enabled:
            self._clear_persistence_store()

        if self.redis_enabled:
            self._load_sessions_from_persistence()

    # === Persistence Helpers ===

    def _init_persistence(self) -> None:
        """Initialisiert optionales Redis-Backend für Session-Persistenz."""
        redis_url = os.getenv("REDIS_URL")

        if not redis_url or Redis is None:
            print("ℹ️ Session-Persistenz deaktiviert – verwende In-Memory Store")
            return

        try:
            self.redis_client = Redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
        except RedisError as exc:
            print(f"⚠️ Redis nicht erreichbar ({exc}). Fallback auf In-Memory Store.")
            self.redis_client = None
            self.redis_enabled = False
            return

        self.redis_enabled = True
        print("✅ Redis Session-Persistenz aktiviert")
        self._load_sessions_from_persistence()

    def _key(self, *parts: str) -> str:
        return ":".join([self.redis_namespace, *parts])

    def _persist_active_sessions(self) -> None:
        if not self.redis_enabled or not self.redis_client:
            return

        if self.active_admin_sessions:
            try:
                payload = json.dumps(sorted(self.active_admin_sessions))
                self.redis_client.set(self._key("session", "active_admin"), payload)
            except RedisError as exc:
                print(f"⚠️ Persistierung der aktiven Sessions fehlgeschlagen: {exc}")
        else:
            self.redis_client.delete(self._key("session", "active_admin"))

    def _persist_session(self, session: Session) -> None:
        if not self.redis_enabled or not self.redis_client:
            return

        try:
            payload = session.to_dict(include_messages=True)
            self.redis_client.set(self._key("session", session.id), json.dumps(payload))
            self.redis_client.sadd(self._key("sessions"), session.id)
        except RedisError as exc:
            print(f"⚠️ Persistierung der Session {session.id} fehlgeschlagen: {exc}")

    def _load_sessions_from_persistence(self) -> None:
        if not self.redis_enabled or not self.redis_client:
            return

        try:
            session_ids = self.redis_client.smembers(self._key("sessions"))
            for session_id in session_ids:
                raw = self.redis_client.get(self._key("session", session_id))
                if not raw:
                    continue
                data = json.loads(raw)
                session = Session.from_dict(data)
                self.sessions[session.id] = session

            stored_active = self.redis_client.get(self._key("session", "active_admin"))
            if stored_active:
                try:
                    payload = json.loads(stored_active)
                    if isinstance(payload, list):
                        self.active_admin_sessions = set(payload)
                    elif isinstance(payload, str):
                        self.active_admin_sessions = {payload}
                except (json.JSONDecodeError, TypeError):
                    self.active_admin_sessions = {stored_active}

                # Stale IDs bereinigen
                self.active_admin_sessions = {
                    sid
                    for sid in self.active_admin_sessions
                    if sid in self.sessions
                    and self.sessions[sid].status != SessionStatus.TERMINATED
                }
        except RedisError as exc:
            print(f"⚠️ Laden der Sessions aus Redis fehlgeschlagen: {exc}")

    def _clear_persistence_store(self) -> None:
        if not self.redis_enabled or not self.redis_client:
            return

        try:
            session_ids = self.redis_client.smembers(self._key("sessions"))
            for session_id in session_ids:
                self.redis_client.delete(self._key("session", session_id))
            self.redis_client.delete(self._key("sessions"))
            self.redis_client.delete(self._key("session", "active_admin"))
        except RedisError as exc:
            print(f"⚠️ Bereinigung des Session-Stores fehlgeschlagen: {exc}")

    async def create_admin_session(self) -> str:
        """Neue Admin-Session erstellen.

        Standardmäßig wird aus Datenschutzgründen genau eine aktive Admin-Session
        gleichzeitig erlaubt. Das bisherige Parallelverhalten kann explizit über
        ``SSF_ALLOW_PARALLEL_SESSIONS=true`` reaktiviert werden.
        """
        await asyncio.sleep(0)
        if not self.allow_parallel_sessions:
            await self.terminate_all_active_sessions(reason="new_session_created")

        session_id = str(uuid.uuid4())[:8].upper()
        session = Session(id=session_id, status=SessionStatus.PENDING)  # Wartet auf Customer-Join
        self.sessions[session_id] = session
        self.active_admin_sessions.add(session_id)

        self._persist_session(session)
        self._persist_active_sessions()

        self._emit_lifecycle(session, SessionLifecyclePhase.CREATED)

        print(f"✅ Neue Admin-Session erstellt: {session_id}")
        return session_id

    async def terminate_all_active_sessions(self, reason: str = "system_cleanup") -> None:
        """Alle aktiven Sessions beenden (manueller Cleanup)"""
        terminated_count = 0
        terminated_session_ids: set[str] = set()

        for session_id, session in tuple(self.sessions.items()):
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]:
                await self.terminate_session(session_id, reason)
                terminated_count += 1
                terminated_session_ids.add(session_id)

        for session_id in terminated_session_ids:
            terminated = self.sessions.get(session_id)
            if terminated is not None:
                terminated.termination_reason = reason
                self._persist_session(terminated)

        if terminated_count > 0:
            print(f"🔄 {terminated_count} Sessions beendet. Grund: {reason}")

        # Active session tracking zurücksetzen
        self.active_admin_sessions.clear()
        self._persist_active_sessions()

    async def terminate_session(self, session_id: str, reason: str = "manual_termination") -> None:
        """Einzelne Session beenden mit WebSocket-Notifications"""
        session = self.get_session(session_id)
        if not session:
            return

        if session.status == SessionStatus.TERMINATED:
            return

        # Legacy session mutation remains process-local and follows its
        # established persistence path.
        session.status = SessionStatus.TERMINATED
        session.terminated_at = self.clock()
        session.termination_reason = reason
        session.admin_connected = False
        session.customer_connected = False
        session.admin_connection_count = 0
        session.customer_connection_count = 0

        self._emit_lifecycle(
            session,
            SessionLifecyclePhase.TERMINATED,
            SessionTerminationReason.classify(reason),
        )

        if session_id in self.active_admin_sessions:
            self.active_admin_sessions.discard(session_id)

        # WebSocket-Disconnect-Notifications senden
        await self._send_termination_notifications(session_id, reason)

        # WebSocket-Verbindungen cleanup
        await self._cleanup_websocket_connections(session_id)

        # Session persistieren
        self._persist_session(session)
        self._persist_active_sessions()

        print(f"🔚 Session {session_id} beendet. Grund: {reason}")

    async def _send_termination_notifications(self, session_id: str, reason: str) -> bool:
        """WebSocket-Benachrichtigungen bei Session-Beendigung"""
        if self.websocket_manager:
            await self.websocket_manager.handle_session_termination(session_id, reason)
            return True

        if session_id not in self.websocket_connections:
            return False

        termination_message = {
            "type": "session_terminated",
            "session_id": session_id,
            "reason": reason,
            "message": self._get_termination_message(reason),
            "timestamp": utc_now().isoformat(),
        }

        # Alle WebSocket-Verbindungen der Session benachrichtigen
        connections = self.websocket_connections.get(session_id, {})
        for client_type, websocket in connections.items():
            try:
                if websocket:
                    await websocket.send_json(termination_message)
                    if hasattr(websocket, "close"):
                        await websocket.close(code=1000, reason=f"Session terminated: {reason}")
            except Exception as e:
                print(f"⚠️ WebSocket-Notification-Fehler ({client_type}): {e}")

        return False

    def _get_termination_message(self, reason: str) -> str:
        """Benutzerfreundliche Termination-Messages"""
        messages = {
            "new_session_created": "Die Session wurde beendet, da eine neue Session gestartet wurde.",
            "timeout": "Die Session wurde aufgrund von Inaktivität beendet.",
            "manual_termination": "Die Session wurde manuell beendet.",
            "manual_admin_termination": "Die Session wurde vom Admin beendet.",
            "system_cleanup": "Die Session wurde für System-Wartung beendet.",
            "error": "Die Session wurde aufgrund eines Fehlers beendet.",
        }
        return messages.get(reason, "Die Session wurde beendet.")

    async def _cleanup_websocket_connections(self, session_id: str) -> None:
        """WebSocket-Connection-Pool cleanup"""
        await asyncio.sleep(0)
        if session_id in self.websocket_connections:
            del self.websocket_connections[session_id]
            print(f"🧹 WebSocket-Connections für Session {session_id} bereinigt")

    def create_session(self, customer_language: str) -> str:
        """Legacy-Methode - deprecated zugunsten von create_admin_session()"""
        print("⚠️ Warning: create_session() ist deprecated. Verwende create_admin_session()")
        session_id = str(uuid.uuid4())[:8].upper()
        session = Session(
            id=session_id,
            customer_language=customer_language,
            status=SessionStatus.ACTIVE,
        )
        self.sessions[session_id] = session
        self._persist_session(session)

        # Both phases: this path opens the session already ACTIVE, with the
        # customer language known, so the transition `activate_session` would
        # otherwise report has already happened -- and its PENDING check would
        # never fire. Emitting only `created` would leave the funnel showing a
        # termination for a session that was never activated.
        self._emit_lifecycle(session, SessionLifecyclePhase.CREATED)
        self._emit_lifecycle(session, SessionLifecyclePhase.ACTIVATED)

        return session_id

    def get_session(self, session_id: str) -> Optional[Session]:
        """Session abrufen"""
        session = self.sessions.get(session_id)
        if session is None and self.redis_enabled and self.redis_client:
            try:
                raw = self.redis_client.get(self._key("session", session_id))
                if raw:
                    data = json.loads(raw)
                    session = Session.from_dict(data)
                    self.sessions[session_id] = session
            except RedisError as exc:
                print(f"⚠️ Lesen der Session {session_id} aus Redis fehlgeschlagen: {exc}")
        return session

    def has_unscoped_session(self, session_id: str) -> bool:
        return self.get_session(session_id) is not None

    def resolve_customer_session(self, session_id: str) -> None:
        """No legacy session has a join index."""
        return None

    def resolve_ended_session(self, session_id: str, *, within: timedelta) -> None:
        """No legacy session leaves a tombstone."""
        return None

    def get_session_status(self, session_id: str) -> Optional[SessionStatus]:
        """Session-Status abrufen"""
        session = self.get_session(session_id)
        return session.status if session else None

    def add_message(self, session_id: str, message: SessionMessage) -> None:
        """Nachricht zur Session hinzufügen"""
        if session := self.get_session(session_id):
            session.messages.append(message)
            # ✨ Session-Aktivität bei neuer Nachricht aktualisieren
            session.update_activity()
            self._persist_session(session)

    def record_message_authorization(
        self,
        session_id: str,
        message_id: str,
        *,
        record: bool,
        original_audio: bool,
        translated_audio: bool,
    ) -> None:
        """Store the outcome of one message's three policy reads."""
        session = self.get_session(session_id)
        if session is None:
            return
        for message in session.messages:
            if message.id != message_id:
                continue
            message.record_authorized = record
            message.original_audio_authorized = original_audio
            message.translated_audio_authorized = translated_audio
            break
        else:
            return
        self._persist_session(session)

    def _persist_swept_session(self, session: Session) -> None:
        if session.tenant_id is None:
            self._persist_session(session)
            return
        raise RuntimeError(_TENANT_STORE_UNAVAILABLE)

    def get_active_session(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Aktive Admin-Session abrufen.

        Wenn eine Session-ID übergeben wird, wird genau diese Session zurückgegeben,
        sofern sie noch nicht beendet wurde. Ohne Session-ID wird die zuletzt erstellte
        aktive Session geliefert, solange diese eindeutig ist.
        """
        if session_id:
            session = self.get_session(session_id)
            if not session or session.status == SessionStatus.TERMINATED:
                return None
            return session.to_dict()

        active_sessions = [
            session
            for session in self.sessions.values()
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]
        ]

        if not active_sessions:
            return None

        if len(active_sessions) > 1:
            raise ValueError("Mehrere aktive Sessions vorhanden; explizite session_id erforderlich")

        active_sessions.sort(key=lambda s: s.created_at, reverse=True)
        return active_sessions[0].to_public_dict()

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Alle aktiven oder ausstehende Sessions zurückgeben."""
        return [
            session.to_public_dict()
            for session in self.sessions.values()
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]
        ]

    def get_session_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Vergangene Sessions für Admin-Dashboard"""
        terminated_sessions = [
            session.to_public_dict()
            for session in self.sessions.values()
            if session.status == SessionStatus.TERMINATED
        ]

        # Nach Beendigungszeit sortieren (neueste zuerst)
        terminated_sessions.sort(key=lambda s: s.get("terminated_at", ""), reverse=True)

        return terminated_sessions[:limit]

    async def activate_session(self, session_id: str, customer_language: str) -> None:
        """Session aktivieren wenn Customer beitritt oder Sprache ändern"""
        await asyncio.sleep(0)
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} nicht gefunden")

        # Erlaubt Aktivierung von PENDING → ACTIVE oder Sprachänderung in ACTIVE
        if session.status == SessionStatus.TERMINATED:
            raise ValueError(
                f"Session {session_id} ist beendet und kann nicht mehr geändert werden"
            )

        session.customer_language = customer_language
        activated = session.status == SessionStatus.PENDING
        if activated:
            session.status = SessionStatus.ACTIVE
        session.customer_connected = True
        self._persist_session(session)

        if activated:
            self._emit_lifecycle(session, SessionLifecyclePhase.ACTIVATED)

        print(f"🎯 Session {session_id} aktiviert/aktualisiert mit Sprache: {customer_language}")

    async def add_websocket_connection(
        self, session_id: str, client_type: ClientType, websocket: Any
    ) -> None:
        """WebSocket-Verbindung zur Session hinzufügen"""
        await asyncio.sleep(0)
        if session_id not in self.websocket_connections:
            self.websocket_connections[session_id] = {}

        self.websocket_connections[session_id][client_type.value] = websocket

        # Session-Status aktualisieren
        session = self.get_session(session_id)
        if session:
            if client_type == ClientType.ADMIN:
                session.admin_connected = True
            else:
                session.customer_connected = True
            self._persist_session(session)

        print(f"🔗 WebSocket-Verbindung hinzugefügt: {session_id} ({client_type.value})")

    async def remove_websocket_connection(self, session_id: str, client_type: ClientType) -> None:
        """WebSocket-Verbindung von Session entfernen"""
        await asyncio.sleep(0)
        if session_id in self.websocket_connections:
            self.websocket_connections[session_id].pop(client_type.value, None)

            # Session-Status aktualisieren
            session = self.get_session(session_id)
            if session:
                if client_type == ClientType.ADMIN:
                    session.admin_connected = False
                else:
                    session.customer_connected = False
                self._persist_session(session)

            print(f"🔌 WebSocket-Verbindung entfernt: {session_id} ({client_type.value})")

    def get_websocket_connection(self, session_id: str, client_type: ClientType) -> Any:
        """WebSocket-Verbindung abrufen"""
        return self.websocket_connections.get(session_id, {}).get(client_type.value)

    # ✨ Timeout Management Functions

    def update_session_activity(self, session_id: str) -> None:
        """Session-Aktivität aktualisieren (Heartbeat/Message)"""
        session = self.get_session(session_id)
        if session:
            session.update_activity()
            self._persist_session(session)

    async def check_session_timeouts(self) -> None:
        """Alle Sessions auf Timeouts prüfen und entsprechende Aktionen durchführen"""
        for session in tuple(self.sessions.values()):
            if session.status == SessionStatus.TERMINATED:
                continue

            if session.is_timeout_warning_due():
                await self._send_timeout_warning(session)
            if session.is_timeout_due():
                await self.terminate_session(session.id, reason="session_timeout")

    async def _send_timeout_warning(self, session: Session) -> None:
        """Timeout-Warning an alle WebSocket-Clients der Session senden"""
        if self.websocket_manager:
            remaining_minutes = session.session_timeout_minutes - session.warning_timeout_minutes

            warning_message = {
                "type": "timeout_warning",
                "session_id": session.id,
                "message": f"Session wird in {remaining_minutes} Minuten aufgrund von Inaktivität beendet.",
                "remaining_minutes": remaining_minutes,
                "timestamp": utc_now().isoformat(),
            }

            await self.websocket_manager.broadcast_to_session(session.id, warning_message)
            session.timeout_warning_sent = True
            self._persist_session(session)

    async def heartbeat_received(self, session_id: str, client_type: ClientType) -> None:
        """Heartbeat von Client empfangen - Aktivität aktualisieren"""
        self.update_session_activity(session_id)

        # Optional: Heartbeat-Response senden
        if self.websocket_manager:
            response = {
                "type": "heartbeat_response",
                "session_id": session_id,
                "client_type": client_type.value,
                "timestamp": utc_now().isoformat(),
            }
            # WebSocketManager has no send_to_client; no production path calls this.
            await self.websocket_manager.send_to_client(  # type: ignore[attr-defined]
                session_id, client_type, response
            )
