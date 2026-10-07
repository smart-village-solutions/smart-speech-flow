"""A conversation's state: the session, its messages, its status and its content settlement."""

from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .clock import utc_now
from .consent import ConsentStatus
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)


class ClientType(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class SessionStatus(str, Enum):
    INACTIVE = "inactive"
    PENDING = "pending"  # Session erstellt, wartet auf Client
    ACTIVE = "active"  # Beide Teilnehmer verbunden
    TERMINATED = "terminated"  # Session beendet


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


# An owner-less session belongs to nobody, so it matches no owner, not even
# another owner-less request.
def _same_owner(stored: Optional[str], requested: Optional[str]) -> bool:
    if stored is None or requested is None:
        return False
    return hmac.compare_digest(stored, requested)


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


_CONFIGURATION_REVISION = re.compile(r"sha256:[0-9a-f]{64}")


def _stored_configuration_revision(data: Dict[str, Any]) -> str:
    """The record's revision; v1 records carry it inside their configuration snapshot."""
    revision = data.get("configuration_revision")
    if revision is None:
        snapshot = data.get("runtime_configuration")
        revision = snapshot.get("configuration_revision") if isinstance(snapshot, dict) else None
    if not isinstance(revision, str) or not _CONFIGURATION_REVISION.fullmatch(revision):
        raise ValueError("session record has no valid configuration revision")
    return revision


def _previous_gateway_snapshot(revision: Optional[str]) -> Optional[Dict[str, str]]:
    """The v1 snapshot shape, so a rollback to the v1 gateway can still load the record.

    That gateway's `from_dict` requires these three keys and never parses
    `canonical_json` outside tests. Drop with the v1 compatibility (Studio v2 PR 14).
    """
    if revision is None:
        return None
    return {
        "configuration_revision": revision,
        "authorization_revision": revision,
        "canonical_json": "{}",
    }


@dataclass
class Session:
    id: str
    # Transitional defaults keep untouched legacy call sites importable while
    # the hard-cut routes are migrated. Persistence rejects missing scope.
    tenant_id: Optional[str] = None
    configuration_revision: Optional[str] = None
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
    # The creating admin (tenant_context.admin_ref). None for sessions stored
    # before owners existed; such a session is never another admin's.
    owner_ref: Optional[str] = None

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

    def is_owned_by(self, owner_ref: Optional[str]) -> bool:
        """Whether ``owner_ref`` created this session; an owner-less session is nobody's."""
        return _same_owner(self.owner_ref, owner_ref)

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
            "configuration_revision": self.configuration_revision,
            "runtime_configuration": _previous_gateway_snapshot(self.configuration_revision),
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
            "owner_ref": self.owner_ref,
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
        data.pop("configuration_revision", None)
        data.pop("runtime_configuration", None)
        data.pop("owner_ref", None)
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
            configuration_revision=_stored_configuration_revision(data),
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
            owner_ref=data.get("owner_ref"),
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


def _unprune_messages(
    previous: list[SessionMessage], pruned: list[SessionMessage], kept: int
) -> list[SessionMessage]:
    """The messages a failed sweep write restores.

    The sweep swaps in a pruned list of copies and awaits its write. What
    changed on that list meanwhile survives the rollback: messages appended
    after its first `kept`, and the authorization recorded on a copy.
    """
    copies = {message.id: message for message in pruned[:kept]}
    for message in previous:
        if (copied := copies.get(message.id)) is not None:
            message.record_authorized = copied.record_authorized
            message.original_audio_authorized = copied.original_audio_authorized
            message.translated_audio_authorized = copied.translated_audio_authorized
    return previous + pruned[kept:]


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
