"""Recording a live conversation: the employee asks, the guest answers (spec §5.2).

Each change is idempotent on its `request_id`, or is a no-op when the state is
already where it leads, so a retried click never makes a second transition.
Either side may stop at any time; only an employee holding
`ssf.recording.request` may ask. The guest's screen fetches the consent text
of the open question here and answers with its hash (§6).
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_ssf_user
from ..dependencies import get_session_manager, optional_container
from ..recording.audit import GUEST_ACTOR
from ..recording.consent_evidence import (
    NAME_MAX_LENGTH,
    SIGNATURE_MAX_BYTES,
    ConsentEvidenceError,
    GuestAnswer,
    decode_signature,
)
from ..recording.consent_text import staff_release
from ..recording.consent_voice import ReadAloudUnavailableError
from ..recording.permissions import REQUEST, coded, permissions_of
from ..recording.session_service import RecordingSessions, RecordingUnavailableError
from ..recording.session_state import Phase, RecordingConflictError, RecordingState
from ..session_access import require_admin_session_key, require_customer_session_key
from ..session_manager import TenantSessionManager
from ..session_models import ClientType
from ..speech_services import AUDIO_WAV_MIME
from ..studio_locales import STAFF_LANGUAGE
from ..tenant_session import TenantSessionKey
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(tags=["recording"], route_class=ValueFreeValidationRoute)

ADMIN = "/api/admin/session/{session_id}/recording"
CUSTOMER = "/api/customer/session/{session_id}/recording"
# Studio unreachable, or the archive failing to record a yes: refusals a retry may cure.
_UNAVAILABLE_STATUS = {"RECORDING_POLICY_UNAVAILABLE": 503, "ARCHIVE_WRITE_FAILED": 503}

Claims = Annotated[dict[str, Any], Depends(require_ssf_user)]
AdminKey = Annotated[TenantSessionKey, Depends(require_admin_session_key)]
GuestKey = Annotated[TenantSessionKey, Depends(require_customer_session_key)]
Manager = Annotated[TenantSessionManager, Depends(get_session_manager)]
# Base64 of the largest accepted PNG, with room for padding.
_SIGNATURE_CHARS: Final[int] = SIGNATURE_MAX_BYTES * 4 // 3 + 4


def get_recording_sessions(request: Request) -> RecordingSessions:
    sessions: RecordingSessions | None = getattr(
        optional_container(request), "recording_sessions", None
    )
    if sessions is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return sessions


Sessions = Annotated[RecordingSessions, Depends(get_recording_sessions)]


class RecordingRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID


class RecordingAskBody(RecordingRequestBody):
    staff_release_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    # A first request only: the employee may type the guest's name for them to confirm.
    guest_name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    id_checked: bool = False


class RecordingAnswerBody(RecordingRequestBody):
    documentation_consent: bool = False
    consent: bool
    # A yes's evidence (§6); a no needs none of it.
    text_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    signature_png: str | None = Field(default=None, max_length=_SIGNATURE_CHARS)
    cannot_sign: bool = False


class PlaybackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    event: Literal["started", "completed"]


def state_body(state: RecordingState) -> dict[str, Any]:
    body: dict[str, Any] = {
        "state": state.phase.value,
        "reason": state.reason.value if state.reason else None,
        "window_id": state.window_id,
        "state_version": state.state_version,
        "since": state.since.isoformat() if state.since else None,
    }
    if state.phase is Phase.ASKING:
        body["request_id"] = state.request_id
        body["consent_kind"] = state.request_kind
    return body


async def _changed(change: Any) -> dict[str, Any]:
    try:
        return state_body(await change)
    except ConsentEvidenceError as error:
        raise coded(error.status, error.code, "The answer lacks what consent needs") from None
    except RecordingUnavailableError as error:
        status = _UNAVAILABLE_STATUS.get(error.code, 409)
        raise coded(status, error.code, "Recording cannot start") from None
    except RecordingConflictError as error:
        raise coded(409, error.code, "Recording is in another state") from None


@router.get(ADMIN)
async def admin_recording_state(
    key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    state = await sessions.state(key)
    reason, id_check, release = None, None, None
    if REQUEST not in permissions_of(claims):
        reason = "PERMISSION_REQUIRED"
    else:
        try:
            policy = await sessions.check_available(key.tenant_id)
            id_check = policy.id_check
            release = staff_release(policy)
        except RecordingUnavailableError as error:
            reason = error.code
    return state_body(state) | {
        "can_request": reason is None,
        "staff_release": release.record() if release is not None else None,
        "unavailable_reason": reason,
        "next_consent_kind": "resume" if state.consented else "first",
        "id_check": id_check,
    }


@router.post(f"{ADMIN}/request")
async def request_recording(
    body: RecordingAskBody, key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    if REQUEST not in permissions_of(claims):
        raise coded(403, "PERMISSION_REQUIRED", "Permission missing")
    name = body.guest_name.strip() if body.guest_name else ""
    return await _changed(
        sessions.request(
            key,
            request_id=str(body.request_id),
            requested_by=claims["sub"],
            proposed_name=name or None,
            id_checked=body.id_checked,
            staff_release_sha256=body.staff_release_sha256,
        )
    )


@router.post(f"{ADMIN}/cancel")
async def cancel_recording(
    body: RecordingRequestBody, key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    return await _changed(
        sessions.cancel(key, request_id=str(body.request_id), actor=claims["sub"])
    )


@router.post(f"{ADMIN}/stop")
async def stop_recording_as_employee(
    key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    return await _changed(sessions.stop(key, role=ClientType.ADMIN, actor=claims["sub"]))


@router.get(CUSTOMER)
async def guest_recording_state(key: GuestKey, sessions: Sessions) -> dict[str, Any]:
    return state_body(await sessions.state(key))


async def _guest_language(manager: TenantSessionManager, key: TenantSessionKey) -> str:
    session = await manager.get_session(key)
    return (session.customer_language if session else None) or STAFF_LANGUAGE


async def _served(sessions: RecordingSessions, key: TenantSessionKey, language: str) -> Any:
    try:
        return await sessions.consent(key, language)
    except RecordingUnavailableError as error:
        raise coded(_UNAVAILABLE_STATUS.get(error.code, 409), error.code, "No text") from None
    except RecordingConflictError as error:
        raise coded(409, error.code, "No open question") from None


@router.get(f"{CUSTOMER}/consent")
async def guest_consent_text(key: GuestKey, sessions: Sessions, manager: Manager) -> dict[str, Any]:
    """The open question's text, sanitised; the screen answers with the hash of this `html`."""
    served = await _served(sessions, key, await _guest_language(manager, key))
    return {
        "request_id": served.request_id,
        "consent_kind": served.kind,
        "language": served.text.language,
        "html": served.text.html,
        "text_sha256": served.text.answer_sha256,
        "accept_label": served.text.accept_label,
        "decline_label": served.text.decline_label,
        "documentation_consent": served.text.documentation_consent,
        "signature": served.signature,
        "proposed_name": served.proposed_name,
    }


@router.get(f"{CUSTOMER}/consent/audio")
async def guest_consent_audio(
    request_id: UUID,
    text_sha256: Annotated[str, Query(pattern="^[0-9a-f]{64}$")],
    request: Request,
    key: GuestKey,
    sessions: Sessions,
    manager: Manager,
) -> Response:
    """The same text read aloud by the TTS service in the guest's language (§6).

    Named by its question and the text's hash, so a screen never plays a clip it
    kept for an earlier question or an earlier version of the text.
    """
    served = await _served(sessions, key, await _guest_language(manager, key))
    if served.request_id != str(request_id):
        raise coded(409, "RECORDING_REQUEST_STALE", "No open question")
    if served.text.answer_sha256 != text_sha256:
        raise coded(409, "CONSENT_TEXT_MISMATCH", "The text has changed")
    container = optional_container(request)
    if container is None:
        raise coded(503, "READ_ALOUD_UNAVAILABLE", "No voice")
    try:
        clip = await sessions.voice.read(
            key, served.text, container.speech_pipeline.speech, container.pipeline_admission
        )
    except ReadAloudUnavailableError as error:
        raise coded(error.status, error.code, "No voice") from None
    return Response(content=clip, media_type=AUDIO_WAV_MIME)


@router.post(f"{CUSTOMER}/answer")
async def answer_recording(
    body: RecordingAnswerBody, key: GuestKey, sessions: Sessions, manager: Manager
) -> dict[str, Any]:
    reply = None
    if body.consent:
        try:
            signature = decode_signature(body.signature_png)
        except ConsentEvidenceError as error:
            raise coded(error.status, error.code, "The signature is not a PNG") from None
        reply = GuestAnswer(
            language=await _guest_language(manager, key),
            text_sha256=body.text_sha256,
            name=body.name,
            signature_png=signature,
            cannot_sign=body.cannot_sign,
            documentation_consent=body.documentation_consent,
        )
    return await _changed(
        sessions.answer(key, request_id=str(body.request_id), consent=body.consent, reply=reply)
    )


@router.post(f"{CUSTOMER}/stop")
async def stop_recording_as_guest(key: GuestKey, sessions: Sessions) -> dict[str, Any]:
    return await _changed(sessions.stop(key, role=ClientType.CUSTOMER, actor=GUEST_ACTOR))


# A report says nothing back: whether it was archived is not the screen's business.
@router.post(f"{ADMIN}/playback", status_code=204)
async def report_playback_as_employee(
    body: PlaybackBody, key: AdminKey, sessions: Sessions
) -> Response:
    await sessions.playback(key, ClientType.ADMIN, str(body.message_id), body.event)
    return Response(status_code=204)


@router.post(f"{CUSTOMER}/playback", status_code=204)
async def report_playback_as_guest(
    body: PlaybackBody, key: GuestKey, sessions: Sessions
) -> Response:
    await sessions.playback(key, ClientType.CUSTOMER, str(body.message_id), body.event)
    return Response(status_code=204)
