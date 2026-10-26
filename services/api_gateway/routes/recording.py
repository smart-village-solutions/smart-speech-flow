"""Staff routes of recording mode: personal keys (spec §8.3).

Any holder of an `ssf.recording.*` permission may hold keys. Enrolment needs
a fresh MFA login, because whoever enrols first decides which key future
recordings are wrapped for.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.crypto.transcript import display_fingerprint
from ..recording.keys import Enrolment, KeyEnrolmentService
from ..recording.permissions import (
    RECORDING_PERMISSIONS,
    coded,
    require_permission,
    require_step_up,
)
from ..recording.repository import KeyAlreadyEnrolledError, RecordingStorageUnavailable
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/admin/recording", tags=["recording"], route_class=ValueFreeValidationRoute
)

RecordingUser = Annotated[dict[str, Any], Depends(require_permission(*RECORDING_PERMISSIONS))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]


def get_key_enrolment(request: Request) -> KeyEnrolmentService:
    service: KeyEnrolmentService | None = getattr(
        optional_container(request), "recording_keys", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


KeyService = Annotated[KeyEnrolmentService, Depends(get_key_enrolment)]


class EnrolmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enc_pub: str = Field(min_length=87, max_length=87)
    sig_pub: str = Field(min_length=87, max_length=87)
    blob: str = Field(min_length=1, max_length=4096)


def _fingerprint_body(raw: bytes) -> dict[str, str]:
    return {"fingerprint": b64url(raw), "fingerprint_display": display_fingerprint(raw)}


@router.get("/keys/me")
async def own_key(
    context: TenantContext, claims: RecordingUser, service: KeyService
) -> dict[str, str]:
    try:
        key = await service.own_key(context.tenant_id, claims["sub"])
    except RecordingStorageUnavailable:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording storage unavailable") from None
    if key is None:
        raise coded(404, "KEY_NOT_ENROLLED", "No personal key is enrolled")
    return {
        "enc_pub": b64url(key.enc_pub),
        "sig_pub": b64url(key.sig_pub),
        "blob": key.blob,
        "created_at": key.created_at.isoformat(),
        **_fingerprint_body(key.fingerprint),
    }


@router.post(
    "/keys",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_step_up)],
)
async def enrol_key(
    body: EnrolmentBody, context: TenantContext, claims: RecordingUser, service: KeyService
) -> dict[str, str]:
    try:
        enrolment = Enrolment(from_b64url(body.enc_pub), from_b64url(body.sig_pub), body.blob)
        fingerprint = await service.enrol(context.tenant_id, claims["sub"], enrolment)
    except ValueError:  # InvalidEnrolment, or base64 that does not decode
        raise coded(422, "INVALID_ENROLMENT", "The keys or the sealed blob are invalid") from None
    except KeyAlreadyEnrolledError:
        raise coded(409, "KEY_ALREADY_ENROLLED", "A personal key is already enrolled") from None
    except RecordingStorageUnavailable:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording storage unavailable") from None
    return _fingerprint_body(fingerprint)
