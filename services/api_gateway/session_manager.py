# services/api_gateway/session_manager.py
"""
Session Management für bidirektionale Admin-Kunde Gespräche.

`TenantSessionManager` is the production path. The str-keyed legacy path lives
in legacy_session_manager.py; the dataclasses and helpers here serve both.
"""

from __future__ import annotations

import asyncio
import copy
import hmac
import logging
import os
import uuid
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    TypeVar,
)

from .consent import ConsentStatus
from .quality_telemetry import SessionLifecyclePhase, SessionTerminationReason
from .session_pseudonym import MISSING_TENANT_REFERENCE, SessionPseudonymizer, tenant_ref
from .session_store import MemoryTenantSessionStore, TenantSessionStore
from .tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

if TYPE_CHECKING:
    from .audio_storage import AudioStore
    from .realtime_ticket import RealtimeTicketStore
    from .runtime_policy import RuntimePolicyGate
    from .websocket import WebSocketManager
    from .websocket_polling_routes import TenantPollingStore

logger = logging.getLogger(__name__)

_SESSION_NOT_FOUND = "session not found"


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
    translated_audio_available: bool = False
    # NEW: Pipeline Metadata
    pipeline_metadata: Optional[Dict[str, Any]] = None
    original_audio_url: Optional[str] = None  # URL to original input audio
    # Whether each artefact's own live policy read authorised keeping it.
    # Defaults are refused, so a record written before consent existed, or a
    # process with no gate bound, retains nothing.
    record_authorized: bool = False
    original_audio_authorized: bool = False
    translated_audio_authorized: bool = False

    def to_dict(self, *, include_authorization: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "sender": self.sender.value,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "timestamp": self.timestamp.isoformat(),
            "translated_audio_available": self.translated_audio_available,
        }
        # Include pipeline metadata if available
        if self.pipeline_metadata:
            data["pipeline_metadata"] = self.pipeline_metadata
        if self.original_audio_url:
            data["original_audio_url"] = self.original_audio_url
        if include_authorization:
            data["record_authorized"] = self.record_authorized
            data["original_audio_authorized"] = self.original_audio_authorized
            data["translated_audio_authorized"] = self.translated_audio_authorized
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMessage":
        return cls(
            id=data["id"],
            sender=ClientType(data["sender"]),
            original_text=data.get("original_text", ""),
            translated_text=data.get("translated_text", ""),
            # Audio bytes belong in the tenant-scoped, retention-managed file
            # store. Ignore legacy Redis payloads that embedded the bytes.
            audio_base64=None,
            source_lang=data.get("source_lang", ""),
            target_lang=data.get("target_lang", ""),
            timestamp=_ensure_utc(datetime.fromisoformat(data["timestamp"])),
            translated_audio_available=bool(data.get("translated_audio_available", False)),
            pipeline_metadata=data.get("pipeline_metadata"),
            original_audio_url=data.get("original_audio_url"),
            record_authorized=bool(data.get("record_authorized", False)),
            original_audio_authorized=bool(data.get("original_audio_authorized", False)),
            translated_audio_authorized=bool(data.get("translated_audio_authorized", False)),
        )


@dataclass
class Session:
    id: str
    # Transitional defaults keep untouched legacy call sites importable while
    # the hard-cut routes are migrated. Persistence rejects missing scope.
    tenant_id: Optional[str] = None
    runtime_configuration: Optional[RuntimeConfigurationSnapshot] = None
    consent_status: ConsentStatus = ConsentStatus.PENDING
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
        absolute_deadline = self.created_at + timedelta(hours=self.maximum_lifetime_hours)
        if self.admin_connection_count > 0:
            return absolute_deadline
        grace_anchor = self.admin_disconnected_at or self.created_at
        reconnect_deadline = grace_anchor + timedelta(minutes=self.reconnect_grace_minutes)
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
        data: Dict[str, Any] = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "runtime_configuration": (
                self.runtime_configuration.to_dict()
                if self.runtime_configuration is not None
                else None
            ),
            "consent_status": self.consent_status.value,
            "customer_language": self.customer_language,
            "admin_language": self.admin_language,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "terminated_at": (self.terminated_at.isoformat() if self.terminated_at else None),
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
            "timeout_at": (self.next_timeout_at().isoformat() if self.tenant_id else None),
        }

        if include_messages:
            data["messages"] = [
                message.to_dict(include_authorization=True) for message in self.messages
            ]

        return data

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialize dashboard-safe session state without tenant internals."""
        data = self.to_dict()
        data.pop("tenant_id", None)
        data.pop("runtime_configuration", None)
        return data

    def update_activity(self) -> None:
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
            _ensure_utc(datetime.fromisoformat(terminated_at_raw)) if terminated_at_raw else None
        )
        last_activity_raw = data.get("last_activity", data["created_at"])
        admin_disconnected_raw = data.get("admin_disconnected_at")

        session = cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            runtime_configuration=RuntimeConfigurationSnapshot.from_dict(
                data["runtime_configuration"]
            ),
            consent_status=ConsentStatus.from_stored(data.get("consent_status")),
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


def _mark_translated_audio_gone(metadata: Optional[Dict[str, Any]]) -> None:
    """Record that a step's translated audio is no longer available.

    `scope_pipeline_audio_urls` rebuilds a translated URL from a step output
    that carries `audio_url` or `audio_available: True`, so both have to stop
    saying the audio is there. The key is set to False rather than removed:
    a step that produced no audio still reports that it produced none.
    """
    if not isinstance(metadata, dict):
        return
    steps = metadata.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        if "audio_url" in output or output.get("audio_available") is True:
            output.pop("audio_url", None)
            output["audio_available"] = False


def _settle_refused_content(session: Session) -> tuple[bool, list[tuple[str, Any]]]:
    """Prune refused messages and report the audio files they leave behind.

    The record is mutated here but no file is touched. Deletion is the
    caller's to perform once the record write has committed: termination
    treats a store failure as transient and retryable, and files removed
    ahead of that commit are gone for a conversation still running.

    Args:
        session: The session whose content is being settled. Its message
            list is replaced in place with the messages that may be kept.

    Returns:
        Whether the record changed, and the artefacts to delete afterwards.
        An artefact removal that keeps the message leaves the count
        identical, so the count alone is the wrong predicate for "this
        needs writing back". A session without a tenant is never settled.
    """
    from .audio_storage import AudioVariant

    if session.tenant_id is None:
        return False, []

    changed = False
    doomed: list[tuple[str, Any]] = []
    retained = []
    for message in session.messages:
        if not message.record_authorized:
            doomed.append((message.id, AudioVariant.ORIGINAL))
            doomed.append((message.id, AudioVariant.TRANSLATED))
            changed = True
            continue
        if _remove_refused_original_audio(message, doomed):
            changed = True
        if message.translated_audio_available and (not message.translated_audio_authorized):
            doomed.append((message.id, AudioVariant.TRANSLATED))
            # A retained message must not advertise audio it no longer has,
            # on either marker: `scope_pipeline_audio_urls` rebuilds a
            # translated URL from the step outputs alone.
            message.translated_audio_available = False
            _mark_translated_audio_gone(message.pipeline_metadata)
            changed = True
        retained.append(message)
    session.messages = retained
    return changed, doomed


def _remove_refused_original_audio(message: SessionMessage, doomed: list[tuple[str, Any]]) -> bool:
    from .audio_storage import AudioVariant

    # An artefact that was never produced reports as unauthorised too,
    # because no read was taken for it. Only clear markers that
    # actually describe audio this message had.
    pipeline_input = (
        message.pipeline_metadata.get("input")
        if isinstance(message.pipeline_metadata, dict)
        else None
    )
    had_original = bool(message.original_audio_url) or (
        isinstance(pipeline_input, dict) and pipeline_input.get("type") == "audio"
    )
    if had_original and not message.original_audio_authorized:
        doomed.append((message.id, AudioVariant.ORIGINAL))
        # Both markers, or `conversation_service` still derives an
        # original-audio URL for a file that is gone.
        message.original_audio_url = None
        if isinstance(pipeline_input, dict):
            pipeline_input.pop("type", None)
        return True
    return False


KeyT = TypeVar("KeyT")
KeyT_contra = TypeVar("KeyT_contra", contravariant=True)


class SessionSockets[KeyT_in](Protocol):
    """What a session manager calls on the realtime side of its app.

    `WebSocketManager` is a `SessionSockets[TenantSessionKey]`. The legacy
    adapter's `SessionSockets[str]` is satisfied only by test doubles now.
    The key is inferred contravariant: it appears only as a parameter.
    """

    async def handle_session_termination(self, session_id: KeyT_in, reason: str) -> None: ...

    async def broadcast_to_session(self, session_id: KeyT_in, message: Dict[str, Any]) -> None: ...


class SessionRegistry(Protocol[KeyT_contra]):
    """What the WebSocket manager needs from a session manager.

    Generic in the key rather than widened to `Any`. The WebSocket manager
    takes a `SessionRegistry[TenantSessionKey]`, which `TenantSessionManager`
    is; `LegacySessionManager` is only a `SessionRegistry[str]`.
    """

    def register_websocket_manager(self, manager: WebSocketManager) -> None: ...

    def get_session(self, session_id: KeyT_contra) -> Optional[Session]: ...

    async def add_websocket_connection(
        self, session_id: KeyT_contra, client_type: ClientType, websocket: Any
    ) -> None: ...

    async def remove_websocket_connection(
        self, session_id: KeyT_contra, client_type: ClientType
    ) -> None: ...


class SessionManagerBase(Generic[KeyT]):
    """The session cache, lifecycle telemetry and content sweep both managers share."""

    quality_telemetry: Optional[Any] = None

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        pseudonymizer: Optional[SessionPseudonymizer],
    ) -> None:
        self.allow_parallel_sessions: bool = _env_flag("SSF_ALLOW_PARALLEL_SESSIONS", False)
        self.clock = clock
        self.pseudonymizer = pseudonymizer or SessionPseudonymizer.from_environment()
        self.sessions: Dict[KeyT, Session] = {}
        self.websocket_manager: Optional[SessionSockets[KeyT]] = None

    def attach_quality_telemetry(self, telemetry: Optional[Any]) -> None:
        """Wired by the gateway's lifespan; None detaches it on teardown."""
        self.quality_telemetry = telemetry

    def register_websocket_manager(self, manager: SessionSockets[KeyT]) -> None:
        """WebSocketManager-Referenz für bidirektionale Cleanup-Prozesse registrieren."""
        self.websocket_manager = manager

    def _emit_lifecycle(
        self,
        session: Session,
        phase: SessionLifecyclePhase,
        reason: SessionTerminationReason = SessionTerminationReason.NONE,
    ) -> None:
        """Never raises. Telemetry must not decide whether a session opens."""
        telemetry = self.quality_telemetry
        if telemetry is None:
            return
        try:
            telemetry.emit_session_lifecycle(
                session_ref=self.pseudonymizer.reference(session.id),
                tenant_ref=(
                    tenant_ref(session.tenant_id) if session.tenant_id else MISSING_TENANT_REFERENCE
                ),
                phase=phase,
                termination_reason=reason,
                session_duration_ms=_session_duration_ms(session),
                message_count=len(session.messages),
            )
        except Exception:  # telemetry must never reach the caller
            logger.warning("Session quality telemetry failed", exc_info=True)

    def _persist_swept_session(self, session: Session) -> None:
        """Write back a session the sweep changed.

        Called only when something actually changed: a sweep that rewrote every
        session on every pass would turn an hourly maintenance task into
        continuous write amplification against Redis.
        """
        raise NotImplementedError

    def _delete_settled_audio(self, key: TenantSessionKey, doomed: list[tuple[str, Any]]) -> None:
        """Delete the artefacts a settled record no longer accounts for.

        Only a tenant session yields any, so only `TenantSessionManager` has an
        audio store to delete them from.
        """
        raise NotImplementedError

    def sweep_expired_content(self, now: datetime) -> Dict[str, int]:
        """Remove refused content past session lifetime, and expired text.

        The two removals are deliberately different. Refused content goes at
        the maximum session lifetime and no operator setting can retain it.
        Authorised content goes at `SSF_CONTENT_RETENTION_HOURS`, which `0`
        disables for the tester environment.

        Args:
            now: The moment to measure both ages against.

        Returns:
            Counts of the messages removed by each rule.
        """
        from .audio_storage import retention_hours

        keep_for = retention_hours()
        refused_removed = 0
        expired_removed = 0

        # Persistence callbacks may change the cache while this pass runs.
        for session in self.sessions.copy().values():
            # A terminated record is immutable in the store -- SAVE_SESSION_LUA
            # refuses every change to one -- so its retention is the expiry set
            # on it at termination, not this sweep. Pruning it here would drift
            # from the store and resurrect on the next load.
            if session.status is SessionStatus.TERMINATED:
                continue
            try:
                refused_delta, expired_delta = self._sweep_session_content(session, now, keep_for)
                refused_removed += refused_delta
                expired_removed += expired_delta
            except Exception:  # noqa: BLE001 - one session must not stop the pass
                logger.warning(
                    "content_sweep_failed",
                    extra={"session_ref": self.pseudonymizer.reference(session.id)},
                )
                continue

        return {
            "refused_removed": refused_removed,
            "expired_removed": expired_removed,
        }

    def _sweep_session_content(
        self, session: Session, now: datetime, keep_for: int
    ) -> tuple[int, int]:
        # Settled on a copy, exactly as termination does. A failed
        # write must leave the live session and its files untouched,
        # or the next pass sees an already-pruned list, computes an
        # empty deletion set, and the refused files are stranded.
        working = replace(session)
        working.messages = [copy.deepcopy(message) for message in session.messages]
        changed = False
        doomed_audio: list[tuple[str, Any]] = []
        refused_delta = 0
        expired_delta = 0
        max_age = timedelta(hours=session.maximum_lifetime_hours)
        if now - session.created_at >= max_age:
            before = len(working.messages)
            changed, doomed_audio = _settle_refused_content(working)
            refused_delta = before - len(working.messages)
        if keep_for:
            cutoff = now - timedelta(hours=keep_for)
            retained = [m for m in working.messages if m.timestamp > cutoff]
            if len(retained) != len(working.messages):
                changed = True
            expired_delta = len(working.messages) - len(retained)
            working.messages = retained
        if not changed:
            return 0, 0

        previous = session.messages
        session.messages = working.messages
        try:
            self._persist_swept_session(session)
        except Exception:
            session.messages = previous
            raise

        # `Session.key` raises without a tenant, and a legacy
        # session never yields artefacts to delete anyway.
        if session.tenant_id is not None and doomed_audio:
            self._delete_settled_audio(session.key, doomed_audio)
        return refused_delta, expired_delta

    def get_sessions_requiring_timeout_check(self) -> List[Session]:
        """Sessions zurückgeben, die Timeout-Checks benötigen"""
        return [
            session
            for session in self.sessions.values()
            if session.status in [SessionStatus.ACTIVE, SessionStatus.PENDING]
        ]


class TenantSessionManager(SessionManagerBase[TenantSessionKey]):
    """Tenant-scoped sessions behind a `TenantSessionStore`.

    Each gateway app builds one in `build_gateway_dependencies`, with the
    app's store, audio store, realtime tickets, polling store, persistence
    gate and pseudonymizer.
    """

    def __init__(
        self,
        *,
        store: TenantSessionStore,
        audio_store: AudioStore,
        realtime_tickets: Optional[RealtimeTicketStore] = None,
        polling_store: Optional[TenantPollingStore] = None,
        runtime_policy: Optional[RuntimePolicyGate] = None,
        pseudonymizer: Optional[SessionPseudonymizer] = None,
        clock: Callable[[], datetime] = utc_now,
        session_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(clock=clock, pseudonymizer=pseudonymizer)
        self.store = store
        # Where settlement and the content sweep delete refused audio.
        self.audio_store = audio_store
        self.realtime_tickets = realtime_tickets
        self.polling_store = polling_store
        # None refuses every write of conversation content.
        self.runtime_policy = runtime_policy
        self.session_id_factory = session_id_factory or (lambda: str(uuid.uuid4())[:8].upper())
        self.active_admin_sessions: Dict[str, set[str]] = {}

    def reset(self, *, clear_persistence: bool = False) -> None:
        """SessionManager Zustand auf Initialwerte zurücksetzen."""
        if clear_persistence and isinstance(self.store, MemoryTenantSessionStore):
            self.store.clear()
        self.sessions = {}
        self.active_admin_sessions = {}
        self.websocket_manager = None

    def _delete_settled_audio(self, key: TenantSessionKey, doomed: list[tuple[str, Any]]) -> None:
        for message_id, variant in doomed:
            self.audio_store.delete(key, message_id, variant)

    def rehydrate_tenant_sessions(self) -> None:
        """Restore active v2 sessions and discard process-local presence.

        Redis connection counts describe sockets owned by the process that
        wrote them. They cannot survive a gateway restart. A previously
        connected administrator receives a fresh reconnect-grace anchor at
        restart; an already disconnected administrator retains its original
        anchor so restarting cannot extend an expired session indefinitely.
        """
        restored = self.store.list_active()
        restarted_at = self.clock()
        for session in restored:
            stale_admin_presence = session.admin_connected or session.admin_connection_count > 0
            session.admin_connected = False
            session.customer_connected = False
            session.admin_connection_count = 0
            session.customer_connection_count = 0
            if stale_admin_presence:
                session.admin_disconnected_at = restarted_at
                session.timeout_warning_sent = False
            elif session.admin_disconnected_at is None:
                session.admin_disconnected_at = session.created_at
            self.store.save(session)
            self.sessions[session.key] = session
            self.active_admin_sessions.setdefault(session.key.tenant_id, set()).add(session.id)

    async def create_admin_session(
        self,
        tenant_id: str,
        runtime_configuration: RuntimeConfigurationSnapshot,
    ) -> Session:
        """Neue Admin-Session erstellen.

        Standardmäßig wird aus Datenschutzgründen genau eine aktive Admin-Session
        je Mandant gleichzeitig erlaubt. Das bisherige Parallelverhalten kann
        explizit über ``SSF_ALLOW_PARALLEL_SESSIONS=true`` reaktiviert werden.
        """
        await asyncio.sleep(0)
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
                timeout_warning_minutes=_positive_env_int("SSF_SESSION_TIMEOUT_WARNING_MINUTES", 5),
                maximum_lifetime_hours=_positive_env_int("SSF_SESSION_MAX_HOURS", 8),
            )
            if self.store.create(session):
                self.sessions[session.key] = session
                self.active_admin_sessions.setdefault(tenant_id, set()).add(session.id)
                self._emit_lifecycle(session, SessionLifecyclePhase.CREATED)
                return session
        raise RuntimeError("could not allocate a globally unique session id")

    async def terminate_all_active_sessions(
        self, reason: str = "system_cleanup", *, tenant_id: str
    ) -> None:
        """Alle aktiven Sessions eines Mandanten beenden."""
        keys = [
            key
            for key, session in tuple(self.sessions.items())
            if hmac.compare_digest(key.tenant_id, tenant_id)
            and session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
        ]
        for key in keys:
            await self.terminate_session(key, reason)

    async def terminate_session(
        self, session_id: TenantSessionKey, reason: str = "manual_termination"
    ) -> None:
        """Einzelne Session beenden mit WebSocket-Notifications"""
        session = self.get_session(session_id)
        if not session:
            return

        if session.status != SessionStatus.TERMINATED:
            self._commit_tenant_termination(session_id, session, reason)

        # Cleanup is deliberately idempotent and also runs for a terminal
        # session. If notification/socket cleanup was interrupted after the
        # Redis commit, a retry can still revoke capabilities and finish it.
        from .realtime_ticket import RealtimeTicketUnavailable

        if self.realtime_tickets is not None:
            try:
                self.realtime_tickets.revoke(session_id)
            except RealtimeTicketUnavailable:
                logger.error(
                    "realtime_ticket_revocation_unavailable",
                    extra={"tenant_ref": session_id.tenant_ref},
                )
        if self.polling_store is not None:
            self.polling_store.terminate(session_id, reason)
        if self.websocket_manager:
            await self.websocket_manager.handle_session_termination(session_id, reason)
        # The yield the socket-pool cleanup always took before returning.
        await asyncio.sleep(0)

    def _commit_tenant_termination(
        self,
        session_id: TenantSessionKey,
        session: Session,
        reason: str,
    ) -> None:
        # Redis termination is the security-sensitive commit point. Keep
        # the cached object and runtime indexes untouched until the atomic
        # record/index/tombstone mutation succeeds, so a transient store
        # failure remains both internally consistent and retryable.
        terminal_session = replace(
            session,
            status=SessionStatus.TERMINATED,
            terminated_at=self.clock(),
            termination_reason=reason,
            admin_connected=False,
            customer_connected=False,
            admin_connection_count=0,
            customer_connection_count=0,
        )
        # `replace` copies the message list by reference, so settling
        # it would reach back into the running conversation and strip
        # audio references from messages whose files are still on disk.
        # The terminal record gets its own messages; the live session
        # is untouched until the commit succeeds.
        terminal_session.messages = [copy.deepcopy(message) for message in session.messages]
        # The pruned message list is part of the record being
        # committed. The files it drops are deleted only once that
        # commit has succeeded: a store failure here is transient and
        # the caller retries, so anything deleted first would be lost
        # for a session that is still live.
        _, doomed_audio = _settle_refused_content(terminal_session)
        committed_terminal: Optional[Session] = self.store.terminate(terminal_session)
        # A store may accept the termination while keeping a terminal
        # record it already held, discarding the payload settled here.
        # Only delete artefacts when this payload is the committed one.
        # `None` means the store reported success without echoing a
        # record, which the fakes do; that is this payload.
        payload_committed = committed_terminal in (None, terminal_session)
        if committed_terminal is None:
            committed_terminal = terminal_session
        if payload_committed and doomed_audio:
            self._delete_settled_audio(session_id, doomed_audio)

        # Preserve references held by handlers while replacing every
        # cached field with Redis' canonical terminal snapshot. This
        # discards any stale mutations made after a committed
        # termination whose response was lost.
        for session_field in fields(Session):
            setattr(
                session,
                session_field.name,
                getattr(committed_terminal, session_field.name),
            )
        tenant_active = self.active_admin_sessions.get(session_id.tenant_id, set())
        tenant_active.discard(session_id.session_id)
        if not tenant_active:
            self.active_admin_sessions.pop(session_id.tenant_id, None)
        self._emit_lifecycle(
            session,
            SessionLifecyclePhase.TERMINATED,
            SessionTerminationReason.classify(reason),
        )

    def get_session(self, session_id: TenantSessionKey) -> Optional[Session]:
        """Session abrufen"""
        session = self.sessions.get(session_id)
        if session is None:
            session = self.store.load(session_id)
            if session is not None:
                self.sessions[session_id] = session
        return session

    def has_unscoped_session(self, session_id: str) -> bool:
        """Always False: a tenant session is reachable only through its key or join index."""
        return False

    def resolve_customer_session(self, session_id: str) -> Optional[TenantSessionKey]:
        key = self.store.resolve_join(session_id)
        if key is None:
            return None
        session = self.get_session(key)
        if session is None or session.status == SessionStatus.TERMINATED:
            return None
        return key

    def resolve_ended_session(
        self, session_id: str, *, within: timedelta
    ) -> Optional[TenantSessionKey]:
        """The key of a session that terminated no longer than ``within`` ago.

        Terminating a session revokes its join link, which is what stops an
        ended conversation being rejoined or observed. It also removed the only
        route from the bare session id a browser holds back to the tenant that
        owns the conversation, so feedback offered in the ended-conversation
        screen was refused as unknown (#324). This reads the tombstone the
        revocation leaves behind. It returns the key alone -- enough to
        attribute a feedback row to its tenant, and no way back into the
        conversation -- and takes the window from the caller rather than
        holding a policy of its own.
        """
        resolved = self.store.resolve_ended_join(session_id)
        if resolved is None:
            return None
        key, terminated_at = resolved
        # An undatable record cannot be shown to be inside the window.
        if terminated_at is None:
            return None
        if _ensure_utc(self.clock()) - _ensure_utc(terminated_at) > within:
            return None
        return key

    def admin_connected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None or session.status == SessionStatus.TERMINATED:
            raise KeyError(_SESSION_NOT_FOUND)
        session.admin_connection_count += 1
        session.admin_connected = True
        session.admin_disconnected_at = None
        session.timeout_warning_sent = False
        self.store.save(session)

    def admin_disconnected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError(_SESSION_NOT_FOUND)
        if session.status == SessionStatus.TERMINATED:
            return
        session.admin_connection_count = max(0, session.admin_connection_count - 1)
        session.admin_connected = session.admin_connection_count > 0
        if session.admin_connection_count == 0:
            session.admin_disconnected_at = self.clock()
        self.store.save(session)

    def customer_connected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None or session.status == SessionStatus.TERMINATED:
            raise KeyError(_SESSION_NOT_FOUND)
        session.customer_connection_count += 1
        session.customer_connected = True
        self.store.save(session)

    def customer_disconnected(self, key: TenantSessionKey) -> None:
        session = self.get_session(key)
        if session is None:
            raise KeyError(_SESSION_NOT_FOUND)
        if session.status == SessionStatus.TERMINATED:
            return
        session.customer_connection_count = max(0, session.customer_connection_count - 1)
        session.customer_connected = session.customer_connection_count > 0
        self.store.save(session)

    def get_session_status(self, session_id: TenantSessionKey) -> Optional[SessionStatus]:
        """Session-Status abrufen"""
        session = self.get_session(session_id)
        return session.status if session else None

    def add_message(self, session_id: TenantSessionKey, message: SessionMessage) -> None:
        """Nachricht zur Session hinzufügen"""
        if session := self.get_session(session_id):
            session.messages.append(message)
            # ✨ Session-Aktivität bei neuer Nachricht aktualisieren
            session.update_activity()
            self.store.save(session)

    def record_message_authorization(
        self,
        session_id: TenantSessionKey,
        message_id: str,
        *,
        record: bool,
        original_audio: bool,
        translated_audio: bool,
    ) -> None:
        """Store the outcome of one message's three policy reads.

        Args:
            session_id: The session key.
            message_id: The message whose outcome this is.
            record: Whether the message record itself may be retained.
            original_audio: Whether the guest's input audio may be retained.
            translated_audio: Whether the synthesised audio may be retained.
        """
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
        self.store.save(session)

    def _persist_swept_session(self, session: Session) -> None:
        self.store.save(session)

    def get_active_session(
        self,
        session_id: Optional[str] = None,
        *,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Aktive Admin-Session eines Mandanten abrufen.

        Wenn eine Session-ID übergeben wird, wird genau diese Session zurückgegeben,
        sofern sie noch nicht beendet wurde. Ohne Session-ID wird die zuletzt erstellte
        aktive Session geliefert, solange diese eindeutig ist.
        """
        candidates = [
            session
            for session in self.store.list_for_tenant(tenant_id)
            if session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
            and (session_id is None or session.id == session_id)
        ]
        if not candidates:
            return None
        if len(candidates) > 1 and session_id is None:
            raise ValueError("Mehrere aktive Sessions vorhanden; explizite session_id erforderlich")
        candidates.sort(key=lambda item: item.created_at, reverse=True)
        return candidates[0].to_public_dict()

    def get_active_sessions(self, *, tenant_id: str) -> List[Dict[str, Any]]:
        """Alle aktiven oder ausstehende Sessions zurückgeben."""
        return [
            session.to_public_dict()
            for session in self.store.list_for_tenant(tenant_id)
            if session.status in (SessionStatus.PENDING, SessionStatus.ACTIVE)
        ]

    def get_session_history(self, limit: int = 10, *, tenant_id: str) -> List[Dict[str, Any]]:
        """Vergangene Sessions für Admin-Dashboard"""
        terminated_sessions = [
            session.to_public_dict()
            for session in self.store.list_for_tenant(tenant_id)
            if session.status == SessionStatus.TERMINATED
        ]
        terminated_sessions.sort(key=lambda item: item.get("terminated_at", ""), reverse=True)
        return terminated_sessions[:limit]

    async def activate_session(self, session_id: TenantSessionKey, customer_language: str) -> None:
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
        # This method doubles as the language-update path, so the transition --
        # not the call -- is what counts. Emitting unconditionally would report
        # one session as activated once per language change.
        activated = session.status == SessionStatus.PENDING
        if activated:
            session.status = SessionStatus.ACTIVE
        session.customer_connected = True
        self.store.save(session)

        if activated:
            self._emit_lifecycle(session, SessionLifecyclePhase.ACTIVATED)

        logger.info(
            "tenant_session_activation tenant_ref=%s session_ref=%s",
            tenant_ref(session_id.tenant_id),
            self.pseudonymizer.reference(session_id.session_id),
        )

    async def add_websocket_connection(
        self, session_id: TenantSessionKey, client_type: ClientType, websocket: Any
    ) -> None:
        """WebSocket-Verbindung zur Session hinzufügen"""
        await asyncio.sleep(0)
        if client_type == ClientType.ADMIN:
            self.admin_connected(session_id)
        else:
            self.customer_connected(session_id)
        logger.info(
            "tenant_websocket_registered",
            extra={"tenant_ref": session_id.tenant_ref},
        )

    async def remove_websocket_connection(
        self, session_id: TenantSessionKey, client_type: ClientType
    ) -> None:
        """WebSocket-Verbindung von Session entfernen"""
        await asyncio.sleep(0)
        if client_type == ClientType.ADMIN:
            self.admin_disconnected(session_id)
        else:
            self.customer_disconnected(session_id)
        logger.info(
            "tenant_websocket_unregistered",
            extra={"tenant_ref": session_id.tenant_ref},
        )

    async def check_session_timeouts(self) -> None:
        """Alle Sessions auf Timeouts prüfen und entsprechende Aktionen durchführen"""
        self._prune_polling_presence()

        for session in tuple(self.sessions.values()):
            if session.status == SessionStatus.TERMINATED:
                continue

            warning_due = session.warning_due(self.clock())
            timeout_due = session.timeout_due(self.clock())
            if warning_due:
                await self._send_timeout_warning(session)
            if timeout_due:
                await self.terminate_session(session.key, reason="session_timeout")

    def _prune_polling_presence(self) -> None:
        if self.polling_store is None:
            return
        for client in self.polling_store.prune():
            try:
                if client.client_type is ClientType.ADMIN:
                    self.admin_disconnected(client.key)
                else:
                    self.customer_disconnected(client.key)
            except KeyError:
                pass

    async def _send_timeout_warning(self, session: Session) -> None:
        """Timeout-Warning an alle WebSocket-Clients der Session senden"""
        if self.websocket_manager:
            remaining_minutes = session.timeout_warning_minutes
            warning_message = {
                "type": "timeout_warning",
                "session_id": session.id,
                "message": f"Session wird in {remaining_minutes} Minuten aufgrund von Inaktivität beendet.",
                "remaining_minutes": remaining_minutes,
                "timestamp": utc_now().isoformat(),
            }

            await self.websocket_manager.broadcast_to_session(session.key, warning_message)
            session.timeout_warning_sent = True
            self.store.save(session)

    async def heartbeat_received(
        self, session_id: TenantSessionKey, client_type: ClientType
    ) -> None:
        """A heartbeat changes no business or timeout state of a tenant session.

        The WebSocket manager answers pings and tracks liveness itself; the
        reconnect grace runs on admin presence, not on heartbeats.
        """
        await asyncio.sleep(0)
