# services/api_gateway/session_manager.py
"""
Session Management für bidirektionale Admin-Kunde Gespräche
Speichert Sessions in-memory (für Entwicklung) oder Redis (für Produktion)
"""

from __future__ import annotations

import uuid
import json
import os
from typing import Dict, List, Optional, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from .websocket import WebSocketManager

from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

try:  # Optional dependency for persistence
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis optional for tests
    Redis = None  # type: ignore
    class RedisError(Exception):  # type: ignore
        pass

class ClientType(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"

class SessionStatus(str, Enum):
    INACTIVE = "inactive"
    PENDING = "pending"  # Session erstellt, wartet auf Client
    ACTIVE = "active"    # Beide Teilnehmer verbunden
    TERMINATED = "terminated"  # Session beendet

@dataclass
class SessionMessage:
    id: str
    sender: ClientType
    original_text: str
    translated_text: str
    audio_base64: Optional[str]
    source_lang: str
    target_lang: str
    timestamp: datetime

    def to_dict(self):
        return {
            "id": self.id,
            "sender": self.sender.value,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "audio_base64": self.audio_base64,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMessage":
        return cls(
            id=data["id"],
            sender=ClientType(data["sender"]),
            original_text=data.get("original_text", ""),
            translated_text=data.get("translated_text", ""),
            audio_base64=data.get("audio_base64"),
            source_lang=data.get("source_lang", ""),
            target_lang=data.get("target_lang", ""),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )

@dataclass
class Session:
    id: str
    customer_language: Optional[str] = None  # Wird erst bei Client-Join gesetzt
    admin_language: str = "de"
    status: SessionStatus = SessionStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    terminated_at: Optional[datetime] = None
    messages: List[SessionMessage] = field(default_factory=list)
    admin_connected: bool = False
    customer_connected: bool = False
    termination_reason: Optional[str] = None

    # ✨ Timeout Management Features
    last_activity: datetime = field(default_factory=datetime.now)
    timeout_warning_sent: bool = False
    session_timeout_minutes: int = 30  # Auto-close nach 30 Minuten
    warning_timeout_minutes: int = 25  # Warning nach 25 Minuten

    def to_dict(self, include_messages: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "customer_language": self.customer_language,
            "admin_language": self.admin_language,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "terminated_at": self.terminated_at.isoformat() if self.terminated_at else None,
            "message_count": len(self.messages),
            "admin_connected": self.admin_connected,
            "customer_connected": self.customer_connected,
            "termination_reason": self.termination_reason,
            "last_activity": self.last_activity.isoformat(),
            "timeout_warning_sent": self.timeout_warning_sent,
            "session_timeout_minutes": self.session_timeout_minutes,
            "warning_timeout_minutes": self.warning_timeout_minutes,
            "minutes_since_activity": int((datetime.now() - self.last_activity).total_seconds() / 60)
        }

        if include_messages:
            data["messages"] = [message.to_dict() for message in self.messages]

        return data

    def update_activity(self):
        """Session-Aktivität aktualisieren (für Heartbeat/Messages)"""
        self.last_activity = datetime.now()
        self.timeout_warning_sent = False

    def is_timeout_warning_due(self) -> bool:
        """Prüft ob Timeout-Warning gesendet werden soll"""
        if self.timeout_warning_sent or self.status != SessionStatus.ACTIVE:
            return False

        minutes_inactive = (datetime.now() - self.last_activity).total_seconds() / 60
        return minutes_inactive >= self.warning_timeout_minutes

    def is_timeout_due(self) -> bool:
        """Prüft ob Session aufgrund Timeout beendet werden soll"""
        if self.status == SessionStatus.TERMINATED:
            return False

        minutes_inactive = (datetime.now() - self.last_activity).total_seconds() / 60
        return minutes_inactive >= self.session_timeout_minutes

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        messages_data = data.get("messages", [])
        messages = [SessionMessage.from_dict(msg) for msg in messages_data]

        created_at = datetime.fromisoformat(data["created_at"])
        terminated_at_raw = data.get("terminated_at")
        terminated_at = datetime.fromisoformat(terminated_at_raw) if terminated_at_raw else None
        last_activity_raw = data.get("last_activity", data["created_at"])

        session = cls(
            id=data["id"],
            customer_language=data.get("customer_language"),
            admin_language=data.get("admin_language", "de"),
            status=SessionStatus(data.get("status", SessionStatus.PENDING.value)),
            created_at=created_at,
            terminated_at=terminated_at,
            messages=messages,
            admin_connected=data.get("admin_connected", False),
            customer_connected=data.get("customer_connected", False),
            termination_reason=data.get("termination_reason"),
            last_activity=datetime.fromisoformat(last_activity_raw),
            timeout_warning_sent=data.get("timeout_warning_sent", False),
            session_timeout_minutes=data.get("session_timeout_minutes", 30),
            warning_timeout_minutes=data.get("warning_timeout_minutes", 25)
        )

        return session

def _set_global_session_manager(manager: SessionManager) -> None:  # type: ignore[name-defined]
    """Global SessionManager-Referenz aktualisieren."""
    global session_manager
    session_manager = manager


class SessionManager:
    _instance: Optional[SessionManager] = None  # type: ignore[name-defined]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.redis_client: Optional[Redis] = None
        self.redis_namespace: str = os.getenv("REDIS_NAMESPACE", "ssf")
        self.redis_enabled: bool = False

        self.reset()
        _set_global_session_manager(self)
        self._init_persistence()

    def reset(self, *, clear_persistence: bool = False):
        """SessionManager Zustand auf Initialwerte zurücksetzen."""
        self.sessions: Dict[str, Session] = {}
        self.websocket_connections: Dict[str, Dict[str, Any]] = {}
        self.active_admin_session: Optional[str] = None  # Single-Session-Tracking
        self.websocket_manager: Optional["WebSocketManager"] = None

        if clear_persistence and self.redis_enabled:
            self._clear_persistence_store()

        if self.redis_enabled:
            self._load_sessions_from_persistence()

    # === Persistence Helpers ===

    def _init_persistence(self):
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

    def _persist_active_session(self):
        if not self.redis_enabled or not self.redis_client:
            return

        if self.active_admin_session:
            self.redis_client.set(self._key("session", "active_admin"), self.active_admin_session)
        else:
            self.redis_client.delete(self._key("session", "active_admin"))

    def _persist_session(self, session: Session):
        if not self.redis_enabled or not self.redis_client:
            return

        try:
            payload = session.to_dict(include_messages=True)
            self.redis_client.set(self._key("session", session.id), json.dumps(payload))
            self.redis_client.sadd(self._key("sessions"), session.id)
        except RedisError as exc:
            print(f"⚠️ Persistierung der Session {session.id} fehlgeschlagen: {exc}")

    def _load_sessions_from_persistence(self):
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
                self.active_admin_session = stored_active
        except RedisError as exc:
            print(f"⚠️ Laden der Sessions aus Redis fehlgeschlagen: {exc}")

    def _clear_persistence_store(self):
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
        """Neue Admin-Session erstellen (Single-Session-Policy)"""
        # 1. Alle bestehenden Sessions beenden
        await self.terminate_all_active_sessions(reason="new_session_created")

        # 2. Neue Session erstellen
        session_id = str(uuid.uuid4())[:8].upper()
        session = Session(
            id=session_id,
            status=SessionStatus.PENDING  # Wartet auf Customer-Join
        )
        self.sessions[session_id] = session
        self.active_admin_session = session_id

        self._persist_session(session)
        self._persist_active_session()

        print(f"✅ Neue Admin-Session erstellt: {session_id}")
        return session_id

    async def terminate_all_active_sessions(self, reason: str = "system_cleanup"):
        """Alle aktiven Sessions beenden (Single-Session-Policy)"""
        terminated_count = 0

        for session_id, session in list(self.sessions.items()):
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]:
                await self.terminate_session(session_id, reason)
                terminated_count += 1

        # Bereits terminierte Sessions optional aktualisieren, um konsistenten Reason zu gewährleisten
        for session in self.sessions.values():
            if session.status == SessionStatus.TERMINATED:
                session.termination_reason = reason
                self._persist_session(session)

        if terminated_count > 0:
            print(f"🔄 {terminated_count} Sessions beendet. Grund: {reason}")

        # Active session tracking zurücksetzen
        self.active_admin_session = None
        self._persist_active_session()

    async def terminate_session(self, session_id: str, reason: str = "manual_termination"):
        """Einzelne Session beenden mit WebSocket-Notifications"""
        session = self.get_session(session_id)
        if not session or session.status == SessionStatus.TERMINATED:
            return

        # Session-Status aktualisieren
        session.status = SessionStatus.TERMINATED
        session.terminated_at = datetime.now()
        session.termination_reason = reason
        session.admin_connected = False
        session.customer_connected = False

        if self.active_admin_session == session_id:
            self.active_admin_session = None

        # WebSocket-Disconnect-Notifications senden
        await self._send_termination_notifications(session_id, reason)

        # WebSocket-Verbindungen cleanup
        await self._cleanup_websocket_connections(session_id)

        # Session persistieren
        self._persist_session(session)
        self._persist_active_session()

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
            "timestamp": datetime.now().isoformat()
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
            "system_cleanup": "Die Session wurde für System-Wartung beendet.",
            "error": "Die Session wurde aufgrund eines Fehlers beendet."
        }
        return messages.get(reason, "Die Session wurde beendet.")

    async def _cleanup_websocket_connections(self, session_id: str):
        """WebSocket-Connection-Pool cleanup"""
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
            status=SessionStatus.ACTIVE
        )
        self.sessions[session_id] = session
        self._persist_session(session)
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

    def add_message(self, session_id: str, message: SessionMessage):
        """Nachricht zur Session hinzufügen"""
        if session := self.get_session(session_id):
            session.messages.append(message)
            # ✨ Session-Aktivität bei neuer Nachricht aktualisieren
            session.update_activity()
            self._persist_session(session)

    def get_active_session(self) -> Optional[Dict]:
        """Aktuelle Admin-Session abrufen (Single-Session-Policy)"""
        if not self.active_admin_session:
            return None

        session = self.get_session(self.active_admin_session)
        if not session or session.status == SessionStatus.TERMINATED:
            self.active_admin_session = None
            self._persist_active_session()
            return None

        return session.to_dict()

    def get_active_sessions(self) -> List[Dict]:
        """Legacy-Methode für Admin-Übersicht (deprecated)"""
        print("⚠️ Warning: get_active_sessions() ist deprecated. Verwende get_active_session()")
        return [
            session.to_dict()
            for session in self.sessions.values()
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]
        ]

    def get_session_history(self, limit: int = 10) -> List[Dict]:
        """Vergangene Sessions für Admin-Dashboard"""
        terminated_sessions = [
            session.to_dict()
            for session in self.sessions.values()
            if session.status == SessionStatus.TERMINATED
        ]

        # Nach Beendigungszeit sortieren (neueste zuerst)
        terminated_sessions.sort(
            key=lambda s: s.get("terminated_at", ""),
            reverse=True
        )

        return terminated_sessions[:limit]

    async def activate_session(self, session_id: str, customer_language: str):
        """Session aktivieren wenn Customer beitritt"""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} nicht gefunden")

        if session.status != SessionStatus.PENDING:
            raise ValueError(f"Session {session_id} ist nicht im PENDING-Status")

        session.customer_language = customer_language
        session.status = SessionStatus.ACTIVE
        session.customer_connected = True
        self._persist_session(session)

        print(f"🎯 Session {session_id} aktiviert mit Sprache: {customer_language}")

    async def add_websocket_connection(self, session_id: str, client_type: ClientType, websocket):
        """WebSocket-Verbindung zur Session hinzufügen"""
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

    async def remove_websocket_connection(self, session_id: str, client_type: ClientType):
        """WebSocket-Verbindung von Session entfernen"""
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

    def register_websocket_manager(self, manager: "WebSocketManager") -> None:
        """WebSocketManager-Referenz für bidirektionale Cleanup-Prozesse registrieren."""
        self.websocket_manager = manager

    def get_websocket_connection(self, session_id: str, client_type: ClientType):
        """WebSocket-Verbindung abrufen"""
        return self.websocket_connections.get(session_id, {}).get(client_type.value)

    # ✨ Timeout Management Functions

    def update_session_activity(self, session_id: str):
        """Session-Aktivität aktualisieren (Heartbeat/Message)"""
        session = self.get_session(session_id)
        if session:
            session.update_activity()
            self._persist_session(session)

    async def check_session_timeouts(self):
        """Alle Sessions auf Timeouts prüfen und entsprechende Aktionen durchführen"""
        current_sessions = list(self.sessions.values())

        for session in current_sessions:
            if session.status == SessionStatus.TERMINATED:
                continue

            # Timeout-Warning prüfen
            if session.is_timeout_warning_due():
                await self._send_timeout_warning(session)

            # Auto-Termination prüfen
            if session.is_timeout_due():
                await self.terminate_session(session.id, reason="session_timeout")

    async def _send_timeout_warning(self, session: Session):
        """Timeout-Warning an alle WebSocket-Clients der Session senden"""
        if self.websocket_manager:
            remaining_minutes = session.session_timeout_minutes - session.warning_timeout_minutes

            warning_message = {
                "type": "timeout_warning",
                "session_id": session.id,
                "message": f"Session wird in {remaining_minutes} Minuten aufgrund von Inaktivität beendet.",
                "remaining_minutes": remaining_minutes,
                "timestamp": datetime.now().isoformat()
            }

            await self.websocket_manager.broadcast_to_session(session.id, warning_message)
            session.timeout_warning_sent = True
            self._persist_session(session)
            print(f"⚠️ Timeout-Warning gesendet für Session {session.id}")

    def get_sessions_requiring_timeout_check(self) -> List[Session]:
        """Sessions zurückgeben, die Timeout-Checks benötigen"""
        return [
            session for session in self.sessions.values()
            if session.status in [SessionStatus.ACTIVE, SessionStatus.PENDING]
        ]

    async def heartbeat_received(self, session_id: str, client_type: ClientType):
        """Heartbeat von Client empfangen - Aktivität aktualisieren"""
        self.update_session_activity(session_id)

        # Optional: Heartbeat-Response senden
        if self.websocket_manager:
            response = {
                "type": "heartbeat_response",
                "session_id": session_id,
                "client_type": client_type.value,
                "timestamp": datetime.now().isoformat()
            }
            await self.websocket_manager.send_to_client(session_id, client_type, response)

# Globale Instanz
session_manager = SessionManager()