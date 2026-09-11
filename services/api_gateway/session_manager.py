# services/api_gateway/session_manager.py
"""
Session Management für bidirektionale Admin-Kunde Gespräche
Speichert Sessions in-memory (für Entwicklung) oder Redis (für Produktion)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from .websocket import WebSocketManager

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from .quality_telemetry import SessionLifecyclePhase, SessionTerminationReason
from .session_pseudonym import session_ref
from .session_store import MemoryTenantSessionStore, TenantSessionStore
from .tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

logger = logging.getLogger(__name__)

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
    ACTIVE = "active"  # Beide Teilnehmer verbunden
    TERMINATED = "terminated"  # Session beendet


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.astimezone().astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_duration_ms(session: "Session") -> int:
    """How long the session ran, in whole milliseconds.

    Measured to ``terminated_at``, falling back to ``created_at`` -- so a
    `created` or `activated` row reports exactly 0, and only a `terminated` row
    carries a duration. Deliberately not "to now": a running session's age is
    not its duration, and every dashboard panel reading this column filters on
    `lifecycle_phase = 'terminated'` for that reason. Measuring to now here
    would silently change emitted data those panels are asserted against, so
    time-to-activation needs its own field rather than a change to this one.

    Legacy sessions restored from Redis can carry naive timestamps, hence
    ``_ensure_utc`` on both ends.
    """
    ended = session.terminated_at or session.created_at
    elapsed = (_ensure_utc(ended) - _ensure_utc(session.created_at)).total_seconds()
    return max(0, int(elapsed * 1000))


def _minutes_since(dt: datetime) -> float:
    """Return minutes since ``dt`` while tolerating legacy naive timestamps."""
    return (utc_now() - _ensure_utc(dt)).total_seconds() / 60


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


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
    # NEW: Pipeline Metadata
    pipeline_metadata: Optional[Dict[str, Any]] = None
    original_audio_url: Optional[str] = None  # URL to original input audio

    def to_dict(self):
        data = {
            "id": self.id,
            "sender": self.sender.value,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "audio_base64": self.audio_base64,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "timestamp": self.timestamp.isoformat(),
        }
        # Include pipeline metadata if available
        if self.pipeline_metadata:
            data["pipeline_metadata"] = self.pipeline_metadata
        if self.original_audio_url:
            data["original_audio_url"] = self.original_audio_url
        return data

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
            timestamp=_ensure_utc(datetime.fromisoformat(data["timestamp"])),
            pipeline_metadata=data.get("pipeline_metadata"),
            original_audio_url=data.get("original_audio_url"),
        )


@dataclass
class Session:
    id: str
    # Transitional defaults keep untouched legacy call sites importable while
    # the hard-cut routes are migrated. Persistence rejects missing scope.
    tenant_id: Optional[str] = None
    runtime_configuration: Optional[RuntimeConfigurationSnapshot] = None
    customer_language: Optional[str] = None  # Wird erst bei Client-Join gesetzt
    admin_language: str = "de"
    status: SessionStatus = SessionStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    terminated_at: Optional[datetime] = None
    messages: List[SessionMessage] = field(default_factory=list)
    admin_connected: bool = False
    customer_connected: bool = False
    termination_reason: Optional[str] = None

    # ✨ Timeout Management Features
    last_activity: datetime = field(default_factory=utc_now)
    timeout_warning_sent: bool = False
    session_timeout_minutes: int = 30  # Auto-close nach 30 Minuten
    warning_timeout_minutes: int = 25  # Warning nach 25 Minuten
    admin_connection_count: int = 0
    customer_connection_count: int = 0
    admin_disconnected_at: Optional[datetime] = None
    reconnect_grace_minutes: int = 30
    timeout_warning_minutes: int = 5
    maximum_lifetime_hours: int = 8

    @property
    def key(self) -> TenantSessionKey:
        if self.tenant_id is None:
            raise ValueError("session has no tenant scope")
        return TenantSessionKey(self.tenant_id, self.id)

    def next_timeout_at(self) -> datetime:
        absolute_deadline = self.created_at + timedelta(
            hours=self.maximum_lifetime_hours
        )
        if self.admin_connection_count > 0:
            return absolute_deadline
        grace_anchor = self.admin_disconnected_at or self.created_at
        reconnect_deadline = grace_anchor + timedelta(
            minutes=self.reconnect_grace_minutes
        )
        return min(absolute_deadline, reconnect_deadline)

    def warning_at(self) -> datetime:
        return self.next_timeout_at() - timedelta(minutes=self.timeout_warning_minutes)

    def warning_due(self, now: datetime) -> bool:
        if self.timeout_warning_sent or self.status == SessionStatus.TERMINATED:
            return False
        current = _ensure_utc(now)
        return self.warning_at() <= current < self.next_timeout_at()

    def timeout_due(self, now: datetime) -> bool:
        if self.status == SessionStatus.TERMINATED:
            return False
        return _ensure_utc(now) >= self.next_timeout_at()

    def to_dict(self, include_messages: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "runtime_configuration": (
                self.runtime_configuration.to_dict()
                if self.runtime_configuration is not None
                else None
            ),
            "customer_language": self.customer_language,
            "admin_language": self.admin_language,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "terminated_at": (
                self.terminated_at.isoformat() if self.terminated_at else None
            ),
            "message_count": len(self.messages),
            "admin_connected": self.admin_connected,
            "customer_connected": self.customer_connected,
            "termination_reason": self.termination_reason,
            "last_activity": self.last_activity.isoformat(),
            "timeout_warning_sent": self.timeout_warning_sent,
            "session_timeout_minutes": self.session_timeout_minutes,
            "warning_timeout_minutes": self.warning_timeout_minutes,
            "minutes_since_activity": int(_minutes_since(self.last_activity)),
            "admin_connection_count": self.admin_connection_count,
            "customer_connection_count": self.customer_connection_count,
            "admin_disconnected_at": (
                self.admin_disconnected_at.isoformat()
                if self.admin_disconnected_at is not None
                else None
            ),
            "reconnect_grace_minutes": self.reconnect_grace_minutes,
            "timeout_warning_minutes": self.timeout_warning_minutes,
            "maximum_lifetime_hours": self.maximum_lifetime_hours,
            "warning_at": self.warning_at().isoformat() if self.tenant_id else None,
            "timeout_at": (
                self.next_timeout_at().isoformat() if self.tenant_id else None
            ),
        }

        if include_messages:
            data["messages"] = [message.to_dict() for message in self.messages]

        return data

    def update_activity(self):
        """Session-Aktivität aktualisieren (für Heartbeat/Messages)"""
        self.last_activity = utc_now()
        self.timeout_warning_sent = False

    def is_timeout_warning_due(self) -> bool:
        """Prüft ob Timeout-Warning gesendet werden soll"""
        if self.timeout_warning_sent or self.status != SessionStatus.ACTIVE:
            return False

        minutes_inactive = _minutes_since(self.last_activity)
        return minutes_inactive >= self.warning_timeout_minutes

    def is_timeout_due(self) -> bool:
        """Prüft ob Session aufgrund Timeout beendet werden soll"""
        if self.status == SessionStatus.TERMINATED:
            return False

        minutes_inactive = _minutes_since(self.last_activity)
        return minutes_inactive >= self.session_timeout_minutes

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        messages_data = data.get("messages", [])
        messages = [SessionMessage.from_dict(msg) for msg in messages_data]

        created_at = _ensure_utc(datetime.fromisoformat(data["created_at"]))
        terminated_at_raw = data.get("terminated_at")
        terminated_at = (
            _ensure_utc(datetime.fromisoformat(terminated_at_raw))
            if terminated_at_raw
            else None
        )
        last_activity_raw = data.get("last_activity", data["created_at"])
        admin_disconnected_raw = data.get("admin_disconnected_at")

        session = cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            runtime_configuration=RuntimeConfigurationSnapshot.from_dict(
                data["runtime_configuration"]
            ),
            customer_language=data.get("customer_language"),
            admin_language=data.get("admin_language", "de"),
            status=SessionStatus(data.get("status", SessionStatus.PENDING.value)),
            created_at=created_at,
            terminated_at=terminated_at,
            messages=messages,
            admin_connected=data.get("admin_connected", False),
            customer_connected=data.get("customer_connected", False),
            termination_reason=data.get("termination_reason"),
            last_activity=_ensure_utc(datetime.fromisoformat(last_activity_raw)),
            timeout_warning_sent=data.get("timeout_warning_sent", False),
            session_timeout_minutes=data.get("session_timeout_minutes", 30),
            warning_timeout_minutes=data.get("warning_timeout_minutes", 25),
            admin_connection_count=data.get("admin_connection_count", 0),
            customer_connection_count=data.get("customer_connection_count", 0),
            admin_disconnected_at=(
                _ensure_utc(datetime.fromisoformat(admin_disconnected_raw))
                if admin_disconnected_raw
                else None
            ),
            reconnect_grace_minutes=data.get("reconnect_grace_minutes", 30),
            timeout_warning_minutes=data.get("timeout_warning_minutes", 5),
            maximum_lifetime_hours=data.get("maximum_lifetime_hours", 8),
        )

        return session


class SessionManager:
    quality_telemetry: Optional[Any] = None

    def __init__(
        self,
        *,
        store: Optional[TenantSessionStore] = None,
        clock: Callable[[], datetime] = utc_now,
        session_id_factory: Optional[Callable[[], str]] = None,
    ):
        self.redis_client: Optional[Redis] = None
        self.redis_namespace: str = os.getenv("REDIS_NAMESPACE", "ssf")
        self.redis_enabled: bool = False
        self.allow_parallel_sessions: bool = _env_flag(
            "SSF_ALLOW_PARALLEL_SESSIONS", False
        )
        self.store = store
        self.clock = clock
        self.session_id_factory = session_id_factory or (
            lambda: str(uuid.uuid4())[:8].upper()
        )
        self.tenant_mode = store is not None

        self.reset()
        if not self.tenant_mode:
            self._init_persistence()

    def attach_quality_telemetry(self, telemetry: Optional[Any]) -> None:
        """Wired by the gateway's lifespan; None detaches it on teardown.

        The manager is a process-wide singleton with no request behind it, so
        it cannot reach `app.state` the way a route dependency does. This
        mirrors how `translation_refiner` receives the same emitter.
        """
        self.quality_telemetry = telemetry

    def _emit_lifecycle(
        self,
        session: "Session",
        phase: SessionLifecyclePhase,
        reason: SessionTerminationReason = SessionTerminationReason.NONE,
    ) -> None:
        """Never raises. Telemetry must not decide whether a session opens."""
        telemetry = self.quality_telemetry
        if telemetry is None:
            return
        try:
            telemetry.emit_session_lifecycle(
                session_ref=session_ref(session.id),
                phase=phase,
                termination_reason=reason,
                session_duration_ms=_session_duration_ms(session),
                message_count=len(session.messages),
            )
        except Exception:  # telemetry must never reach the caller
            logger.warning("Session quality telemetry failed", exc_info=True)

    def reset(self, *, clear_persistence: bool = False):
        """SessionManager Zustand auf Initialwerte zurücksetzen."""
        if clear_persistence and isinstance(self.store, MemoryTenantSessionStore):
            self.store.clear()
        if self.tenant_mode:
            self.sessions: Dict[Any, Session] = {}
            self.websocket_connections: Dict[Any, Dict[str, Any]] = {}
            self.active_admin_sessions: Any = {}
        else:
            self.sessions = {}
            self.websocket_connections = {}
            self.active_admin_sessions = set()
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

    def _persist_active_sessions(self):
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

    async def create_admin_session(
        self,
        tenant_id: Optional[str] = None,
        runtime_configuration: Optional[RuntimeConfigurationSnapshot] = None,
    ) -> Any:
        """Neue Admin-Session erstellen.

        Standardmäßig wird aus Datenschutzgründen genau eine aktive Admin-Session
        gleichzeitig erlaubt. Das bisherige Parallelverhalten kann explizit über
        ``SSF_ALLOW_PARALLEL_SESSIONS=true`` reaktiviert werden.
        """
        await asyncio.sleep(0)
        if tenant_id is not None and runtime_configuration is not None:
            return await self._create_tenant_admin_session(
                tenant_id, runtime_configuration
            )
        if not self.allow_parallel_sessions:
            await self.terminate_all_active_sessions(reason="new_session_created")

        session_id = str(uuid.uuid4())[:8].upper()
        session = Session(
            id=session_id, status=SessionStatus.PENDING
        )  # Wartet auf Customer-Join
        self.sessions[session_id] = session
        self.active_admin_sessions.add(session_id)

        self._persist_session(session)
        self._persist_active_sessions()

        self._emit_lifecycle(session, SessionLifecyclePhase.CREATED)

        print(f"✅ Neue Admin-Session erstellt: {session_id}")
        return session_id

    async def _create_tenant_admin_session(
        self,
        tenant_id: str,
        runtime_configuration: RuntimeConfigurationSnapshot,
    ) -> Session:
        if self.store is None:
            self.store = MemoryTenantSessionStore()
        if not self.allow_parallel_sessions:
            await self.terminate_all_active_sessions(
                reason="new_session_created", tenant_id=tenant_id
            )
        for _attempt in range(32):
            created_at = self.clock()
            session = Session(
                id=self.session_id_factory(),
                tenant_id=tenant_id,
                runtime_configuration=runtime_configuration,
                status=SessionStatus.PENDING,
                created_at=created_at,
                last_activity=created_at,
                admin_disconnected_at=created_at,
                reconnect_grace_minutes=_positive_env_int(
                    "SSF_SESSION_RECONNECT_GRACE_MINUTES", 30
                ),
                timeout_warning_minutes=_positive_env_int(
                    "SSF_SESSION_TIMEOUT_WARNING_MINUTES", 5
                ),
                maximum_lifetime_hours=_positive_env_int("SSF_SESSION_MAX_HOURS", 8),
            )
            if self.store.create(session):
                self.sessions[session.key] = session
                self.active_admin_sessions.setdefault(tenant_id, set()).add(session.id)
                self._emit_lifecycle(session, SessionLifecyclePhase.CREATED)
                return session
        raise RuntimeError("could not allocate a globally unique session id")

    async def terminate_all_active_sessions(
        self, reason: str = "system_cleanup", tenant_id: Optional[str] = None
    ):
        """Alle aktiven Sessions beenden (manueller Cleanup)"""
        if tenant_id is not None:
            keys = [
                key
                for key, session in tuple(self.sessions.items())
                if isinstance(key, TenantSessionKey)
                and hmac.compare_digest(key.tenant_id, tenant_id)
                and session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
            ]
            for key in keys:
                await self.terminate_session(key, reason)
            return
        terminated_count = 0
        terminated_session_ids: set[str] = set()

        for session_id, session in tuple(self.sessions.items()):
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]:
                await self.terminate_session(session_id, reason)
                terminated_count += 1
                terminated_session_ids.add(session_id)

        for session_id in terminated_session_ids:
            session = self.sessions.get(session_id)
            if session is not None:
                session.termination_reason = reason
                self._persist_session(session)

        if terminated_count > 0:
            print(f"🔄 {terminated_count} Sessions beendet. Grund: {reason}")

        # Active session tracking zurücksetzen
        self.active_admin_sessions.clear()
        self._persist_active_sessions()

    async def terminate_session(
        self, session_id: Any, reason: str = "manual_termination"
    ):
        """Einzelne Session beenden mit WebSocket-Notifications"""
        session = self.get_session(session_id)
        if not session or session.status == SessionStatus.TERMINATED:
            return

        # Session-Status aktualisieren
        session.status = SessionStatus.TERMINATED
        session.terminated_at = utc_now()
        session.termination_reason = reason
        session.admin_connected = False
        session.customer_connected = False

        # Emitted here rather than after the notifications below: this is the
        # last point at which the session's own state is the reason it ended.
        # A WebSocket failure further down must not lose the row.
        self._emit_lifecycle(
            session,
            SessionLifecyclePhase.TERMINATED,
            SessionTerminationReason.classify(reason),
        )

        if isinstance(session_id, TenantSessionKey):
            tenant_active = self.active_admin_sessions.get(session_id.tenant_id, set())
            tenant_active.discard(session_id.session_id)
            if not tenant_active:
                self.active_admin_sessions.pop(session_id.tenant_id, None)
            if self.store is None:
                raise RuntimeError("tenant session store is unavailable")
            self.store.terminate(session)
            return

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

    async def _send_termination_notifications(
        self, session_id: str, reason: str
    ) -> bool:
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
                        await websocket.close(
                            code=1000, reason=f"Session terminated: {reason}"
                        )
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

    async def _cleanup_websocket_connections(self, session_id: str):
        """WebSocket-Connection-Pool cleanup"""
        await asyncio.sleep(0)
        if session_id in self.websocket_connections:
            del self.websocket_connections[session_id]
            print(f"🧹 WebSocket-Connections für Session {session_id} bereinigt")

    def create_session(self, customer_language: str) -> str:
        """Legacy-Methode - deprecated zugunsten von create_admin_session()"""
        print(
            "⚠️ Warning: create_session() ist deprecated. Verwende create_admin_session()"
        )
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

    def get_session(self, session_id: Any) -> Optional[Session]:
        """Session abrufen"""
        if isinstance(session_id, TenantSessionKey):
            session = self.sessions.get(session_id)
            if session is None and self.store is not None:
                session = self.store.load(session_id)
                if session is not None:
                    self.sessions[session_id] = session
            return session
        session = self.sessions.get(session_id)
        if session is None and self.redis_enabled and self.redis_client:
            try:
                raw = self.redis_client.get(self._key("session", session_id))
                if raw:
                    data = json.loads(raw)
                    session = Session.from_dict(data)
                    self.sessions[session_id] = session
            except RedisError as exc:
                print(
                    f"⚠️ Lesen der Session {session_id} aus Redis fehlgeschlagen: {exc}"
                )
        return session

    def resolve_customer_session(self, session_id: str) -> Optional[TenantSessionKey]:
        if self.store is None:
            return None
        key = self.store.resolve_join(session_id)
        if key is None:
            return None
        session = self.get_session(key)
        if session is None or session.status == SessionStatus.TERMINATED:
            return None
        return key

    def admin_connected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError("session not found")
        session.admin_connection_count += 1
        session.admin_connected = True
        session.admin_disconnected_at = None
        session.timeout_warning_sent = False
        if self.store is not None:
            self.store.save(session)

    def admin_disconnected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError("session not found")
        session.admin_connection_count = max(0, session.admin_connection_count - 1)
        session.admin_connected = session.admin_connection_count > 0
        if session.admin_connection_count == 0:
            session.admin_disconnected_at = self.clock()
        if self.store is not None:
            self.store.save(session)

    def customer_connected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError("session not found")
        session.customer_connection_count += 1
        session.customer_connected = True
        if self.store is not None:
            self.store.save(session)

    def customer_disconnected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError("session not found")
        session.customer_connection_count = max(
            0, session.customer_connection_count - 1
        )
        session.customer_connected = session.customer_connection_count > 0
        if self.store is not None:
            self.store.save(session)

    def get_session_status(self, session_id: str) -> Optional[SessionStatus]:
        """Session-Status abrufen"""
        session = self.get_session(session_id)
        return session.status if session else None

    def add_message(self, session_id: Any, message: SessionMessage):
        """Nachricht zur Session hinzufügen"""
        if session := self.get_session(session_id):
            session.messages.append(message)
            # ✨ Session-Aktivität bei neuer Nachricht aktualisieren
            session.update_activity()
            if isinstance(session_id, TenantSessionKey):
                if self.store is None:
                    raise RuntimeError("tenant session store is unavailable")
                self.store.save(session)
            else:
                self._persist_session(session)

    def get_active_session(
        self,
        session_id: Optional[str] = None,
        *,
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Aktive Admin-Session abrufen.

        Wenn eine Session-ID übergeben wird, wird genau diese Session zurückgegeben,
        sofern sie noch nicht beendet wurde. Ohne Session-ID wird die zuletzt erstellte
        aktive Session geliefert, solange diese eindeutig ist.
        """

        if tenant_id is not None:
            if self.store is None:
                return None
            candidates = [
                session
                for session in self.store.list_for_tenant(tenant_id)
                if session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
                and (session_id is None or session.id == session_id)
            ]
            if not candidates:
                return None
            if len(candidates) > 1 and session_id is None:
                raise ValueError(
                    "Mehrere aktive Sessions vorhanden; explizite session_id erforderlich"
                )
            candidates.sort(key=lambda item: item.created_at, reverse=True)
            return candidates[0].to_dict()

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
            raise ValueError(
                "Mehrere aktive Sessions vorhanden; explizite session_id erforderlich"
            )

        active_sessions.sort(key=lambda s: s.created_at, reverse=True)
        return active_sessions[0].to_dict()

    def get_active_sessions(self, *, tenant_id: Optional[str] = None) -> List[Dict]:
        """Alle aktiven oder ausstehende Sessions zurückgeben."""
        if tenant_id is not None:
            if self.store is None:
                return []
            return [
                session.to_dict()
                for session in self.store.list_for_tenant(tenant_id)
                if session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
            ]
        return [
            session.to_dict()
            for session in self.sessions.values()
            if session.status in [SessionStatus.PENDING, SessionStatus.ACTIVE]
        ]

    def get_session_history(
        self, limit: int = 10, *, tenant_id: Optional[str] = None
    ) -> List[Dict]:
        """Vergangene Sessions für Admin-Dashboard"""
        if tenant_id is not None:
            if self.store is None:
                return []
            terminated_sessions = [
                session.to_dict()
                for session in self.store.list_for_tenant(tenant_id)
                if session.status == SessionStatus.TERMINATED
            ]
            terminated_sessions.sort(
                key=lambda item: item.get("terminated_at", ""), reverse=True
            )
            return terminated_sessions[:limit]
        terminated_sessions = [
            session.to_dict()
            for session in self.sessions.values()
            if session.status == SessionStatus.TERMINATED
        ]

        # Nach Beendigungszeit sortieren (neueste zuerst)
        terminated_sessions.sort(key=lambda s: s.get("terminated_at", ""), reverse=True)

        return terminated_sessions[:limit]

    async def activate_session(self, session_id: Any, customer_language: str):
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

        # Sprache und Status aktualisieren
        session.customer_language = customer_language
        # This method doubles as the language-update path, so the transition --
        # not the call -- is what counts. Emitting unconditionally would report
        # one session as activated once per language change.
        activated = session.status == SessionStatus.PENDING
        if activated:
            session.status = SessionStatus.ACTIVE
        session.customer_connected = True
        if isinstance(session_id, TenantSessionKey):
            if self.store is None:
                raise RuntimeError("tenant session store is unavailable")
            self.store.save(session)
        else:
            self._persist_session(session)

        if activated:
            self._emit_lifecycle(session, SessionLifecyclePhase.ACTIVATED)

        print(
            f"🎯 Session {session_id} aktiviert/aktualisiert mit Sprache: {customer_language}"
        )

    async def add_websocket_connection(
        self, session_id: str, client_type: ClientType, websocket
    ):
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

        print(
            f"🔗 WebSocket-Verbindung hinzugefügt: {session_id} ({client_type.value})"
        )

    async def remove_websocket_connection(
        self, session_id: str, client_type: ClientType
    ):
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

            print(
                f"🔌 WebSocket-Verbindung entfernt: {session_id} ({client_type.value})"
            )

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
        current_sessions = tuple(self.sessions.values())

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
            remaining_minutes = (
                session.session_timeout_minutes - session.warning_timeout_minutes
            )

            warning_message = {
                "type": "timeout_warning",
                "session_id": session.id,
                "message": f"Session wird in {remaining_minutes} Minuten aufgrund von Inaktivität beendet.",
                "remaining_minutes": remaining_minutes,
                "timestamp": utc_now().isoformat(),
            }

            await self.websocket_manager.broadcast_to_session(
                session.id, warning_message
            )
            session.timeout_warning_sent = True
            self._persist_session(session)
            print(f"⚠️ Timeout-Warning gesendet für Session {session.id}")

    def get_sessions_requiring_timeout_check(self) -> List[Session]:
        """Sessions zurückgeben, die Timeout-Checks benötigen"""
        return [
            session
            for session in self.sessions.values()
            if session.status in [SessionStatus.ACTIVE, SessionStatus.PENDING]
        ]

    async def heartbeat_received(self, session_id: Any, client_type: ClientType):
        """Heartbeat von Client empfangen - Aktivität aktualisieren"""
        if not isinstance(session_id, TenantSessionKey):
            self.update_session_activity(session_id)

        # Optional: Heartbeat-Response senden
        if self.websocket_manager:
            response = {
                "type": "heartbeat_response",
                "session_id": (
                    session_id.session_id
                    if isinstance(session_id, TenantSessionKey)
                    else session_id
                ),
                "client_type": client_type.value,
                "timestamp": utc_now().isoformat(),
            }
            await self.websocket_manager.send_to_client(
                session_id, client_type, response
            )


# Globale Instanz
session_manager = SessionManager(store=MemoryTenantSessionStore())
