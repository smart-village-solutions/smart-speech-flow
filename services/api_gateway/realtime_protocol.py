"""The realtime protocol: every frame the gateway sends to a socket or a poller.

Each server frame has a TypedDict and one builder, and no other module writes
a frame as a dict literal (tests/test_realtime_protocol_guard.py). Clients
parse these frames by key, so a builder's keys, fixed values and key order
are the wire contract that tests/gateway_contract/test_contract_realtime_frames.py
pins.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict
from uuid import uuid4

if TYPE_CHECKING:
    from .session_manager import ClientType

# A frame as the transports send it: any builder's TypedDict, or a relayed envelope.
Frame = Mapping[str, Any]


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class MessageType(str, Enum):
    # System Messages
    CONNECTION_ACK = "connection_ack"
    HEARTBEAT_PING = "heartbeat_ping"
    HEARTBEAT_PONG = "heartbeat_pong"
    SESSION_TERMINATED = "session_terminated"
    CONNECTION_STATUS = "connection_status"
    TIMEOUT_WARNING = "timeout_warning"

    # Communication Messages
    MESSAGE = "message"
    TYPING_INDICATOR = "typing_indicator"
    CLIENT_JOINED = "client_joined"
    CLIENT_LEFT = "client_left"

    # 📱 Mobile-Optimization Messages
    TAB_VISIBILITY_CHANGE = "tab_visibility_change"
    BATTERY_STATUS_UPDATE = "battery_status_update"
    NETWORK_STATUS_CHANGE = "network_status_change"
    POLLING_INTERVAL_UPDATE = "polling_interval_update"
    BATTERY_SAVER_MODE = "battery_saver_mode"

    # Error Messages
    ERROR = "error"


_TERMINATION_TEXTS = {
    "new_session_created": "Die Session wurde beendet, da eine neue Session gestartet wurde.",
    "timeout": "Die Session wurde aufgrund von Inaktivität beendet.",
    "manual_termination": "Die Session wurde manuell beendet.",
    "system_cleanup": "Die Session wurde für System-Wartung beendet.",
    "error": "Die Session wurde aufgrund eines Fehlers beendet.",
    "session_ended": "Die Session wurde ordnungsgemäß beendet.",
}
# Every other reason, the admin's own termination and a session timeout included.
_DEFAULT_TERMINATION_TEXT = "Die Session wurde beendet."

BATTERY_SAVER_INTERVAL = 60
_BATTERY_SAVER_TIPS = [
    "📱 Tab schließen wenn nicht benötigt",
    "🔌 Gerät ans Ladegerät anschließen",
    "⚡ Battery-Saver-Modus deaktivieren für normale Geschwindigkeit",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionAckFrame(TypedDict):
    type: str
    session_id: str
    client_type: str
    timestamp: str
    heartbeat_interval: float


class HeartbeatPingFrame(TypedDict):
    type: str
    ping_id: str
    timestamp: str


class ErrorFrame(TypedDict):
    type: str
    error: str
    timestamp: str


class ConnectionStatusFrame(TypedDict):
    type: str
    status: str
    reason: str
    timestamp: str


class ClientJoinedFrame(TypedDict):
    type: str
    session_id: str
    client_type: str
    connection_id: str
    timestamp: str
    customer_language: NotRequired[str]


class ClientLeftFrame(TypedDict):
    type: str
    session_id: str
    client_type: str
    connection_id: str
    reason: str
    timestamp: str


# "from" is a keyword, so these two use the functional syntax.
RelayedMessageFrame = TypedDict(
    "RelayedMessageFrame",
    {"type": str, "from": str, "session_id": str, "content": Any, "timestamp": str},
)
TypingFrame = TypedDict(
    "TypingFrame",
    {"type": str, "from": str, "session_id": str, "is_typing": Any, "timestamp": str},
)


class SessionTerminatedFrame(TypedDict):
    type: str
    session_id: str
    reason: str
    message: str
    timestamp: str
    reconnect_allowed: bool


class PolledSessionTerminatedFrame(TypedDict):
    type: str
    session_id: str
    reason: str
    reconnect_allowed: bool


class TimeoutWarningFrame(TypedDict):
    type: str
    session_id: str
    message: str
    remaining_minutes: int
    timestamp: str


class PollingIntervalUpdateFrame(TypedDict):
    type: str
    new_interval: int
    old_interval: int
    reason: str
    optimization_tips: list[str]
    battery_level: float
    is_mobile: bool
    tab_active: bool
    timestamp: str


class BatterySaverFrame(TypedDict):
    type: str
    title: str
    message: str
    battery_level: float
    new_polling_interval: int
    tips: list[str]
    timestamp: str


class PolledEnvelopeFrame(TypedDict):
    """What a poller's `send` relays: its own type and content, stamped by the server."""

    type: str
    content: dict[str, Any]
    session_id: str
    client_type: str


class SenderConfirmationFrame(TypedDict):
    type: str
    message_id: str
    session_id: str
    text: str
    source_lang: str
    target_lang: str
    sender: str
    timestamp: str
    audio_available: bool
    role: str
    pipeline_metadata: NotRequired[dict[str, Any]]
    original_audio_url: NotRequired[str]


class ReceiverMessageFrame(TypedDict):
    type: str
    message_id: str
    session_id: str
    text: str
    source_lang: str
    target_lang: str
    sender: str
    timestamp: str
    audio_available: bool
    audio_url: str | None
    role: str
    pipeline_metadata: NotRequired[dict[str, Any]]
    original_audio_url: NotRequired[str]


def connection_ack_frame(
    session_id: str, client_type: ClientType, heartbeat_interval: float
) -> ConnectionAckFrame:
    return {
        "type": MessageType.CONNECTION_ACK.value,
        "session_id": session_id,
        "client_type": client_type.value,
        "timestamp": _timestamp(),
        "heartbeat_interval": heartbeat_interval,
    }


def heartbeat_ping_frame() -> HeartbeatPingFrame:
    return {
        "type": MessageType.HEARTBEAT_PING.value,
        "ping_id": uuid4().hex,
        "timestamp": _timestamp(),
    }


def error_frame(error: str) -> ErrorFrame:
    return {"type": MessageType.ERROR.value, "error": error, "timestamp": _timestamp()}


def disconnecting_frame(reason: str) -> ConnectionStatusFrame:
    return {
        "type": MessageType.CONNECTION_STATUS.value,
        "status": "disconnecting",
        "reason": reason,
        "timestamp": _timestamp(),
    }


def client_joined_frame(
    session_id: str,
    client_type: ClientType,
    connection_id: str,
    customer_language: str | None = None,
) -> ClientJoinedFrame:
    frame: ClientJoinedFrame = {
        "type": MessageType.CLIENT_JOINED.value,
        "session_id": session_id,
        "client_type": client_type.value,
        "connection_id": connection_id,
        "timestamp": _timestamp(),
    }
    if customer_language:
        frame["customer_language"] = customer_language
    return frame


def client_left_frame(
    session_id: str, client_type: ClientType, connection_id: str, reason: str
) -> ClientLeftFrame:
    return {
        "type": MessageType.CLIENT_LEFT.value,
        "session_id": session_id,
        "client_type": client_type.value,
        "connection_id": connection_id,
        "reason": reason,
        "timestamp": _timestamp(),
    }


def relayed_message_frame(sender: ClientType, session_id: str, content: Any) -> RelayedMessageFrame:
    return {
        "type": MessageType.MESSAGE.value,
        "from": sender.value,
        "session_id": session_id,
        "content": content,
        "timestamp": _timestamp(),
    }


def typing_frame(sender: ClientType, session_id: str, is_typing: Any) -> TypingFrame:
    return {
        "type": MessageType.TYPING_INDICATOR.value,
        "from": sender.value,
        "session_id": session_id,
        "is_typing": is_typing,
        "timestamp": _timestamp(),
    }


def termination_text(reason: str) -> str:
    return _TERMINATION_TEXTS.get(reason, _DEFAULT_TERMINATION_TEXT)


def session_terminated_frame(session_id: str, reason: str) -> SessionTerminatedFrame:
    return {
        "type": MessageType.SESSION_TERMINATED.value,
        "session_id": session_id,
        "reason": reason,
        "message": termination_text(reason),
        "timestamp": _timestamp(),
        "reconnect_allowed": False,
    }


def polled_session_terminated_frame(session_id: str, reason: str) -> PolledSessionTerminatedFrame:
    """The poller's termination frame, which has never carried a text or a timestamp."""
    return {
        "type": MessageType.SESSION_TERMINATED.value,
        "session_id": session_id,
        "reason": reason,
        "reconnect_allowed": False,
    }


def timeout_warning_frame(session_id: str, remaining_minutes: int) -> TimeoutWarningFrame:
    return {
        "type": MessageType.TIMEOUT_WARNING.value,
        "session_id": session_id,
        "message": (
            f"Session wird in {remaining_minutes} Minuten aufgrund von Inaktivität beendet."
        ),
        "remaining_minutes": remaining_minutes,
        "timestamp": _timestamp(),
    }


def polling_interval_update_frame(
    *,
    new_interval: int,
    old_interval: int,
    reason: str,
    optimization_tips: list[str],
    battery_level: float,
    is_mobile: bool,
    tab_active: bool,
) -> PollingIntervalUpdateFrame:
    return {
        "type": MessageType.POLLING_INTERVAL_UPDATE.value,
        "new_interval": new_interval,
        "old_interval": old_interval,
        "reason": reason,
        "optimization_tips": optimization_tips,
        "battery_level": battery_level,
        "is_mobile": is_mobile,
        "tab_active": tab_active,
        "timestamp": _timestamp(),
    }


def battery_saver_frame(battery_level: float) -> BatterySaverFrame:
    return {
        "type": MessageType.BATTERY_SAVER_MODE.value,
        "title": "🔋 Battery-Saver aktiviert",
        "message": "Update-Frequenz wurde auf 60 Sekunden reduziert um Akku zu schonen.",
        "battery_level": battery_level,
        "new_polling_interval": BATTERY_SAVER_INTERVAL,
        "tips": list(_BATTERY_SAVER_TIPS),
        "timestamp": _timestamp(),
    }


def polled_envelope_frame(
    message_type: str, content: dict[str, Any], session_id: str, client_type: ClientType
) -> PolledEnvelopeFrame:
    return {
        "type": message_type,
        "content": content,
        "session_id": session_id,
        "client_type": client_type.value,
    }


def sender_confirmation_frame(
    *,
    message_id: str,
    session_id: str,
    text: str,
    source_lang: str,
    target_lang: str,
    sender: str,
    timestamp: str,
    pipeline_metadata: dict[str, Any] | None,
    original_audio_url: str | None,
) -> SenderConfirmationFrame:
    """The sender's confirmation of its own message: its original text, no translated audio."""
    frame: SenderConfirmationFrame = {
        "type": MessageType.MESSAGE.value,
        "message_id": message_id,
        "session_id": session_id,
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "sender": sender,
        "timestamp": timestamp,
        "audio_available": False,
        "role": "sender_confirmation",
    }
    if pipeline_metadata is not None:
        frame["pipeline_metadata"] = pipeline_metadata
    if original_audio_url is not None:
        frame["original_audio_url"] = original_audio_url
    return frame


def receiver_message_frame(
    *,
    message_id: str,
    session_id: str,
    text: str,
    source_lang: str,
    target_lang: str,
    sender: str,
    timestamp: str,
    audio_url: str | None,
    pipeline_metadata: dict[str, Any] | None,
    original_audio_url: str | None,
) -> ReceiverMessageFrame:
    """The translation as the other party receives it, with its own role's audio URLs."""
    frame: ReceiverMessageFrame = {
        "type": MessageType.MESSAGE.value,
        "message_id": message_id,
        "session_id": session_id,
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "sender": sender,
        "timestamp": timestamp,
        "audio_available": audio_url is not None,
        "audio_url": audio_url,
        "role": "receiver_message",
    }
    if pipeline_metadata is not None:
        frame["pipeline_metadata"] = pipeline_metadata
    if original_audio_url is not None:
        frame["original_audio_url"] = original_audio_url
    return frame
