"""Recording a live conversation: the employee asks, the guest answers (spec §5.2).

Each change is idempotent on its `request_id`, or is a no-op when the state is
already where it leads, so a retried click never makes a second transition.
Either side may stop at any time; only an employee holding
`ssf.recording.request` may ask.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from ..auth import require_ssf_user
from ..dependencies import optional_container
from ..recording.permissions import REQUEST, coded, permissions_of
from ..recording.session_service import (
    GUEST_ACTOR,
    RecordingSessions,
    RecordingUnavailableError,
)
from ..recording.session_state import Phase, RecordingConflictError, RecordingState
from ..session_access import require_admin_session_key, require_customer_session_key
from ..session_models import ClientType
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


class RecordingAnswerBody(RecordingRequestBody):
    consent: bool


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
    except RecordingUnavailableError as error:
        status = _UNAVAILABLE_STATUS.get(error.code, 409)
        raise coded(status, error.code, "Recording cannot start") from None
    except RecordingConflictError as error:
        raise coded(409, error.code, "Recording is in another state") from None


@router.get(ADMIN)
async def admin_recording_state(
    key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    body = state_body(await sessions.state(key))
    reason = None
    if REQUEST not in permissions_of(claims):
        reason = "PERMISSION_REQUIRED"
    else:
        try:
            await sessions.check_available(key.tenant_id)
        except RecordingUnavailableError as error:
            reason = error.code
    return body | {"can_request": reason is None, "unavailable_reason": reason}


@router.post(f"{ADMIN}/request")
async def request_recording(
    body: RecordingRequestBody, key: AdminKey, claims: Claims, sessions: Sessions
) -> dict[str, Any]:
    if REQUEST not in permissions_of(claims):
        raise coded(403, "PERMISSION_REQUIRED", "Permission missing")
    return await _changed(
        sessions.request(key, request_id=str(body.request_id), requested_by=claims["sub"])
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


@router.post(f"{CUSTOMER}/answer")
async def answer_recording(
    body: RecordingAnswerBody, key: GuestKey, sessions: Sessions
) -> dict[str, Any]:
    return await _changed(
        sessions.answer(key, request_id=str(body.request_id), consent=body.consent)
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
