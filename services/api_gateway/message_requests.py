"""Reading and checking a message request, and storing its audio."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Final, Mapping, Optional

from fastapi import HTTPException, Request, UploadFile
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect

from .audio_processing import AudioValidator
from .audio_storage import AudioStore, AudioVariant
from .log_safety import redacted_exception_info, sanitize_log_value
from .message_models import SUPPORTED_LANGUAGES, TextMessageRequest, create_error_response
from .session_manager import ClientType
from .studio_runtime_flow import correlation_id_from_request
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)


def _safe_identifier(value: Optional[str]) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _log_session_event(message: str, session_id: Optional[str], **extra: Any) -> None:
    safe_extra = {"session_ref": _safe_identifier(session_id)}
    safe_extra.update(sanitize_log_value(extra))
    logger.info("%s | %s", message, safe_extra)


@dataclass(frozen=True)
class _LanguageRule:
    """Which session languages one sender must use, and how a mismatch is worded."""

    source_attribute: str
    source_message: str
    target_attribute: str
    target_message: str


_LANGUAGE_RULES: Final[Mapping[ClientType, _LanguageRule]] = {
    ClientType.CUSTOMER: _LanguageRule(
        "customer_language",
        "Customer must send messages in session language '{expected}', not '{actual}'",
        "admin_language",
        "Customer messages must be translated to admin language '{expected}', not '{actual}'",
    ),
    ClientType.ADMIN: _LanguageRule(
        "admin_language",
        "Admin must send messages in admin language '{expected}', not '{actual}'",
        "customer_language",
        "Admin messages must be translated to customer language '{expected}', not '{actual}'",
    ),
}


def validate_session_languages(
    session: Any,
    source_lang: str,
    target_lang: str,
    client_type: ClientType,
) -> None:
    """Refuse a message whose languages do not match the session (400).

    Customer → admin: customer_language → admin_language.
    Admin → customer: admin_language → customer_language.
    The source is checked first.
    """
    _log_session_event(
        "🔍 Validating languages",
        session.id,
        client=client_type.value,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    rule = _LANGUAGE_RULES.get(client_type)
    if rule is None:
        return
    checks = (
        ("source", rule.source_attribute, rule.source_message, source_lang),
        ("target", rule.target_attribute, rule.target_message, target_lang),
    )
    for side, attribute, message, actual in checks:
        expected = getattr(session, attribute)
        if actual != expected:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": message.format(expected=expected, actual=actual),
                    "error_type": f"INVALID_{side.upper()}_LANGUAGE",
                    "details": {
                        f"expected_{side}_lang": expected,
                        f"actual_{side}_lang": actual,
                        "session_id": session.id,
                    },
                },
            )


def _validate_supported_languages(source_lang: str, target_lang: str) -> None:
    if source_lang in SUPPORTED_LANGUAGES and target_lang in SUPPORTED_LANGUAGES:
        return

    raise HTTPException(
        status_code=400,
        detail=create_error_response(
            "UNSUPPORTED_LANGUAGE",
            f"Unsupported language. Source: {source_lang}, Target: {target_lang}",
            {"supported_languages": list(SUPPORTED_LANGUAGES.keys())},
        ),
    )


async def _parse_audio_form(request: Request) -> tuple[Any, Any, Any]:
    try:
        form = await request.form()
    except (StarletteHTTPException, ValueError, ClientDisconnect):
        # Starlette refuses some bodies with its own HTTPException, the parent of
        # FastAPI's, and lets python-multipart's parse errors (ValueErrors) escape.
        # A client that drops mid-body is its own error too, not a server fault.
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_FORM_DATA", "Malformed form data", {}),
        ) from None
    required_fields = ["file", "source_lang", "target_lang"]
    missing_fields = [field for field in required_fields if field not in form]
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "MISSING_FIELDS",
                f"Missing required fields: {', '.join(missing_fields)}",
                {"missing_fields": missing_fields},
            ),
        )

    return (
        form["file"],
        form["source_lang"],
        form["target_lang"],
    )


def _validate_audio_file_input(file: Any) -> None:
    if hasattr(file, "read"):
        return

    raise HTTPException(
        status_code=400,
        detail=create_error_response("INVALID_FILE", "Invalid audio file", {}),
    )


def _should_validate_upload_file(file: Any) -> bool:
    return isinstance(file, (UploadFile, StarletteUploadFile))


def _validate_audio_payload(file: Any, file_bytes: bytes, validator: AudioValidator) -> bytes:
    if not _should_validate_upload_file(file):
        return file_bytes

    validation_result = validator.validate(file_bytes, normalize=True)
    if validation_result.is_valid:
        return validation_result.processed_audio or file_bytes

    raise HTTPException(
        status_code=400,
        detail=create_error_response(
            validation_result.error_code or "AUDIO_VALIDATION_FAILED",
            validation_result.error_message or "Audio validation failed",
            {
                "validation_details": validation_result.details,
                "validation_time_ms": validation_result.validation_time_ms,
            },
        ),
    )


def _correlation_id_for(request: Request) -> str:
    """The caller's correlation ID, or a fresh one for this write.

    Validated rather than forwarded raw: an unvalidated value reaches the
    policy gate, whose blanket except would turn Studio's `ValueError` into a
    silent refusal to persist -- a retention switch operated by the caller.
    """
    return correlation_id_from_request(request)


def _store_audio_artifacts(
    key: TenantSessionKey,
    _sender: ClientType,
    message_id: str,
    file_bytes: bytes,
    *,
    audio_store: AudioStore,
) -> bool:
    original_audio_available = False
    try:
        audio_store.save(key, message_id, AudioVariant.ORIGINAL, file_bytes)
        original_audio_available = True
    except Exception as e:
        # See _store_translated_audio: success is still reported to the
        # caller, so a warning here is invisible in practice.
        logger.exception(
            "⚠️ Failed to save original audio: %s",
            type(e).__name__,
            exc_info=redacted_exception_info(e),
        )

    return original_audio_available


def _store_translated_audio(
    key: TenantSessionKey,
    message_id: str,
    audio_bytes: Optional[bytes],
    *,
    audio_store: AudioStore,
) -> bool:
    """Save the synthesised reply, reporting whether the listener can play it."""
    if not audio_bytes:
        return False
    try:
        audio_store.save(key, message_id, AudioVariant.TRANSLATED, audio_bytes)
    except Exception as error:
        # Logged at error, not warning: the pipeline still answers
        # successfully, so this line is the only signal that the reply
        # reached the customer with no audio to play.
        logger.exception(
            "⚠️ Failed to save translated audio: %s",
            type(error).__name__,
            exc_info=redacted_exception_info(error),
        )
        return False
    return True


async def _parse_text_request(request: Request) -> TextMessageRequest:
    body = None
    try:
        body = await request.json()
        logger.info(
            "📦 Received JSON payload metadata | %s",
            sanitize_log_value(
                {
                    "keys": sorted(body.keys()) if isinstance(body, dict) else [],
                    "has_text": (bool(body.get("text")) if isinstance(body, dict) else False),
                }
            ),
        )
    except (ValueError, RecursionError, ClientDisconnect) as e:
        # JSONDecodeError and UnicodeDecodeError are ValueErrors; deep nesting recurses;
        # a client that drops mid-body is its own error, not a server fault.
        logger.exception("❌ Failed to parse JSON", exc_info=redacted_exception_info(e))
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_JSON", "Invalid JSON", {}),
        )

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_JSON", "Invalid JSON", {}),
        )
    try:
        return TextMessageRequest(**body)
    except ValidationError as e:
        raise _build_text_validation_error(e, body) from e


def _build_text_validation_error(
    e: ValidationError, body: Optional[Dict[str, Any]]
) -> HTTPException:
    error_details: Mapping[str, Any] = e.errors()[0] if e.errors() else {}
    error_type = error_details.get("type", "unknown")
    field_name = error_details.get("loc", ["unknown"])[-1]

    if error_type == "string_too_long":
        max_length = error_details.get("ctx", {}).get("max_length", 500)
        actual_length = len(body.get(field_name, "")) if body and field_name in body else "unknown"
        user_message = (
            f"Der Text ist zu lang. Maximum: {max_length} Zeichen, "
            f"Ihre Eingabe: {actual_length} Zeichen."
        )
    elif error_type == "string_too_short":
        min_length = error_details.get("ctx", {}).get("min_length", 1)
        user_message = f"Der Text ist zu kurz. Minimum: {min_length} Zeichen."
    elif error_type == "missing":
        user_message = f"Pflichtfeld '{field_name}' fehlt."
    else:
        user_message = (
            f"Ungültige Eingabe für Feld '{field_name}': "
            f"{error_details.get('msg', 'Validierungsfehler')}"
        )

    logger.error(
        "❌ Validation failed | %s",
        sanitize_log_value({"field": field_name, "error_type": error_type}),
    )
    return HTTPException(
        status_code=400,
        detail=create_error_response(
            "VALIDATION_ERROR",
            user_message,
            {"field": field_name, "error_type": error_type},
        ),
    )
