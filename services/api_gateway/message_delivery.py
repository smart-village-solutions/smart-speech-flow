"""Recording a processed message on its session and delivering it to the session's sockets."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from .audio_storage import AudioVariant, scope_pipeline_audio_urls, scoped_audio_url
from .consent import ConsentStatus
from .log_safety import redacted_exception_info, sanitize_log_value
from .message_models import utc_now
from .message_requests import _log_session_event, _safe_identifier
from .persistence_authorization import authorize_message_artifacts
from .realtime_dispatch import BroadcastResult
from .realtime_protocol import receiver_message_frame, sender_confirmation_frame
from .session_manager import TenantSessionManager
from .session_models import ClientType, SessionMessage
from .tenant_session import TenantSessionKey
from .websocket import WebSocketManager

logger = logging.getLogger(__name__)


def _nothing_delivered() -> BroadcastResult:
    """What a broadcast reports when there is no WebSocket manager to deliver through."""
    return BroadcastResult(
        success=True,
        total_connections=0,
        successful_sends=0,
        failed_sends=0,
        session_has_connections=False,
        errors=[],
    )


async def _session_consent_status(
    key: TenantSessionKey, sessions: TenantSessionManager
) -> ConsentStatus:
    """The session's resolved consent, or `pending` when it cannot be read."""
    session = await sessions.get_session(key)
    if session is None:
        return ConsentStatus.PENDING
    return session.consent_status


async def create_session_message(
    session_id: TenantSessionKey,
    client_type: ClientType,
    original_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    manager: Optional[WebSocketManager] = None,
    pipeline_metadata: Optional[Dict[str, Any]] = None,
    original_audio_url: Optional[str] = None,
    message_id: Optional[str] = None,  # Allow pre-generated message_id
    correlation_id: Optional[str] = None,
    *,
    sessions: TenantSessionManager,
    translated_audio_available: bool,
) -> SessionMessage:
    """Session-Message erstellen und zur Session hinzufügen.

    Both audio variants are already stored by the caller; the message only
    records whether each is available.
    """
    import logging

    logger = logging.getLogger(__name__)

    resolved_message_id = message_id or str(uuid.uuid4())

    message = SessionMessage(
        id=resolved_message_id,
        sender=client_type,
        original_text=original_text,
        translated_text=translated_text,
        audio_base64=None,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=utc_now(),
        translated_audio_available=translated_audio_available,
        pipeline_metadata=pipeline_metadata,
        original_audio_url=original_audio_url,
    )

    # Zur Session hinzufügen
    await sessions.add_message(session_id, message)

    # ✨ WebSocket Broadcasting mit differentiated content
    _log_session_event(
        "🔄 Starte WebSocket-Broadcasting",
        session_id.session_id,
        sender=client_type.value,
    )
    try:
        # Only attempt broadcasting if a WebSocketManager was provided
        if manager is not None:
            result = await broadcast_message_to_session(session_id, message, client_type, manager)
        else:
            # No manager available (e.g., unit tests running without DI)
            result = _nothing_delivered()

        # Task 4.7: Handle broadcast failures
        if result.success:
            _log_session_event(
                "✅ WebSocket-Broadcasting erfolgreich",
                session_id.session_id,
                successful_sends=result.successful_sends,
                total_connections=result.total_connections,
            )
        else:
            logger.error(
                "❌ WebSocket-Broadcasting fehlgeschlagen | %s",
                sanitize_log_value(
                    {
                        "session_ref": _safe_identifier(session_id.session_id),
                        "successful_sends": result.successful_sends,
                        "failed_sends": result.failed_sends,
                        "total_connections": result.total_connections,
                        "error_count": len(result.errors),
                    }
                ),
            )
    except Exception as e:
        logger.exception(
            "❌ WebSocket-Broadcasting-Fehler",
            exc_info=redacted_exception_info(e),
        )
        # WebSocket-Fehler sollen den HTTP-Request nicht zum Absturz bringen

    # Only now, with every participant served, does persistence get its say.
    # Each artefact carries its own live read; the outcome decides what
    # survives termination, never what the conversation delivered.
    authorization = await authorize_message_artifacts(
        gate=sessions.runtime_policy,
        tenant_id=session_id.tenant_id,
        consent_status=await _session_consent_status(session_id, sessions),
        correlation_id=correlation_id or str(uuid.uuid4()),
        has_original_audio=original_audio_url is not None,
        has_translated_audio=translated_audio_available,
    )
    message.record_authorized = authorization.record
    message.original_audio_authorized = authorization.original_audio
    message.translated_audio_authorized = authorization.translated_audio
    try:
        await sessions.record_message_authorization(
            session_id,
            resolved_message_id,
            record=authorization.record,
            original_audio=authorization.original_audio,
            translated_audio=authorization.translated_audio,
        )
    except Exception:  # noqa: BLE001 - the message is already delivered
        # The policy reads leave a window in which the session can terminate,
        # and the store then refuses the write-back. Failing the request here
        # would report an error for a message the other party already has, and
        # a retry would duplicate it. The record defaults to refused, so the
        # content this loses is content nothing will retain.
        logger.warning(
            "persistence_authorization_not_recorded | %s",
            sanitize_log_value({"session_ref": _safe_identifier(session_id.session_id)}),
        )

    return message


def _role_scoped_artifacts(
    message: SessionMessage,
    key: TenantSessionKey,
    role: ClientType,
    has_original_audio: bool,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """The pipeline metadata and original-audio URL as `role` may see them, where present."""
    metadata = (
        scope_pipeline_audio_urls(message.pipeline_metadata, key, role.value, message.id)
        if message.pipeline_metadata
        else None
    )
    original = (
        scoped_audio_url(key, role.value, message.id, AudioVariant.ORIGINAL)
        if has_original_audio
        else None
    )
    return metadata, original


async def broadcast_message_to_session(
    session_id: TenantSessionKey,
    message: SessionMessage,
    sender_type: ClientType,
    manager: Optional[WebSocketManager] = None,
) -> BroadcastResult:
    """
    🚀 Differentiated Message Broadcasting:
    - Sender erhält original_text (ASR-Bestätigung)
    - Empfänger erhält translated_text + audio

    Args:
        session_id: Session identifier
        message: Message to broadcast
        sender_type: Who sent the message (admin or customer)
        manager: WebSocketManager instance (injected via dependency injection)

    Returns:
        BroadcastResult with success status and metrics
    """
    _log_session_event(
        "📡 Broadcasting message",
        session_id.session_id,
        sender_type=sender_type.value,
    )

    receiver_type = ClientType.CUSTOMER if sender_type is ClientType.ADMIN else ClientType.ADMIN

    pipeline_input = (
        message.pipeline_metadata.get("input")
        if isinstance(message.pipeline_metadata, dict)
        else None
    )
    has_original_audio = bool(message.original_audio_url) or (
        isinstance(pipeline_input, dict) and pipeline_input.get("type") == "audio"
    )

    # Original Message für Sender (ASR-Bestätigung)
    sender_metadata, sender_original = _role_scoped_artifacts(
        message, session_id, sender_type, has_original_audio
    )
    sender_message = sender_confirmation_frame(
        message_id=message.id,
        session_id=session_id.session_id,
        text=message.original_text,  # 👈 Sender sieht original Text
        source_lang=message.source_lang,
        target_lang=message.target_lang,
        sender=message.sender.value,
        timestamp=message.timestamp.isoformat(),
        pipeline_metadata=sender_metadata,
        original_audio_url=sender_original,
    )

    # Translated Message für Empfänger (mit Audio)
    receiver_metadata, receiver_original = _role_scoped_artifacts(
        message, session_id, receiver_type, has_original_audio
    )
    receiver_message = receiver_message_frame(
        message_id=message.id,
        session_id=session_id.session_id,
        text=message.translated_text,  # 👈 Empfänger sieht übersetzten Text
        source_lang=message.source_lang,
        target_lang=message.target_lang,
        sender=message.sender.value,
        timestamp=message.timestamp.isoformat(),
        audio_url=(
            scoped_audio_url(
                session_id,
                receiver_type.value,
                message.id,
                AudioVariant.TRANSLATED,
            )
            if message.translated_audio_available
            else None
        ),
        pipeline_metadata=receiver_metadata,
        original_audio_url=receiver_original,
    )

    # 🎯 Differentiated Broadcasting ausführen
    _log_session_event("📤 Broadcasting differentiated content", session_id.session_id)
    if manager is None:
        # No WebSocketManager provided (e.g., unit tests without DI) -> noop
        result = _nothing_delivered()
    else:
        result = await manager.broadcast_with_differentiated_content(
            session_id=session_id,
            sender_type=sender_type,
            original_message=sender_message,
            translated_message=receiver_message,
        )
    _log_session_event(
        "✅ Broadcast completed",
        session_id.session_id,
        successful_sends=result.successful_sends,
        total_connections=result.total_connections,
    )
    return result
