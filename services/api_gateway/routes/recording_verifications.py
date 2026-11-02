"""Requesting verification of an archived conversation (spec §10.7).

Whoever may open the conversation lists eligible reviewers and assigns one.
Assigning hands content to another person, so it needs step-up.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.crypto.transcript import display_fingerprint
from ..recording.permissions import (
    RECORDING_PERMISSIONS,
    SUPERVISE,
    coded,
    permissions_of,
    require_permission,
    require_step_up,
)
from ..recording.verification import VerificationError, Verifications
from ..recording.verification_model import (
    MAX_WRAPS,
    AssignRequest,
    AssignWrap,
    Candidate,
    VerificationRow,
)
from ..studio_recording_directory_client import SUB_PATTERN
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/admin/recording/archive",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

RecordingUser = Annotated[dict[str, Any], Depends(require_permission(*RECORDING_PERMISSIONS))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
# A 64-byte P1363 signature, base64url without padding.
_SIGNATURE_CHARACTERS: Final[int] = 86
ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "not_found": (404, "CONVERSATION_NOT_FOUND"),
    "verification_not_found": (404, "VERIFICATION_NOT_FOUND"),
    "not_a_reviewer": (409, "NOT_A_REVIEWER"),
    "reviewer_not_eligible": (409, "REVIEWER_NOT_ELIGIBLE"),
    "assignment_exists": (409, "ASSIGNMENT_EXISTS"),
    "key_changed": (409, "KEY_CHANGED"),
    "reviewer_key_changed": (409, "REVIEWER_KEY_CHANGED"),
    "not_started": (409, "NOT_STARTED"),
    "verification_closed": (409, "VERIFICATION_CLOSED"),
    "head_changed": (409, "HEAD_CHANGED"),
    "permissions_changed": (409, "PERMISSIONS_CHANGED"),
    "signature_invalid": (422, "SIGNATURE_INVALID"),
    "scope_not_covered": (422, "SCOPE_NOT_COVERED"),
    "bad_notes": (422, "BAD_NOTES"),
    "directory_unavailable": (503, "DIRECTORY_UNAVAILABLE"),
    "unavailable": (503, "RECORDING_UNAVAILABLE"),
}


def get_verifications(request: Request) -> Verifications:
    service: Verifications | None = getattr(
        optional_container(request), "recording_verifications", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Service = Annotated[Verifications, Depends(get_verifications)]


def refused(error: VerificationError) -> HTTPException:
    status_code, code = ANSWERS.get(error.code, (503, "RECORDING_UNAVAILABLE"))
    return coded(status_code, code, "The verification request was refused")


class WrapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: uuid.UUID
    blob: str = Field(min_length=1, max_length=2_048)
    signature: str = Field(min_length=_SIGNATURE_CHARACTERS, max_length=_SIGNATURE_CHARACTERS)


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_version: int = Field(ge=1, le=10_000)
    reviewer_sub: str = Field(pattern=SUB_PATTERN.pattern)
    reviewer_key_version: int = Field(ge=1, le=10_000)
    wraps: list[WrapBody] = Field(min_length=1, max_length=MAX_WRAPS)


def _time(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def record_body(row: VerificationRow) -> dict[str, Any]:
    """The clear fields of a record; decided content is added where its reader may see it."""
    return {
        "verification_id": row.verification_id,
        "conversation_id": row.conversation_id,
        "status": row.status,
        "requested_by": row.requested_by,
        "requested_at": row.requested_at.isoformat(),
        "reviewer_sub": row.reviewer_sub,
        "reviewer_key_version": row.reviewer_key_version,
        "reviewer_fingerprint": b64url(row.reviewer_fingerprint),
        "started_at": _time(row.started_at),
        "reviewed_head_seq": row.reviewed_head_seq,
        "reviewed_head": None if row.reviewed_head is None else b64url(row.reviewed_head),
        "permission_snapshot": (
            None if row.permission_snapshot is None else list(row.permission_snapshot)
        ),
        "decided_at": _time(row.decided_at),
        "closed_at": _time(row.closed_at),
        "close_reason": row.close_reason,
    }


def _candidate_body(candidate: Candidate) -> dict[str, Any]:
    return {
        "sub": candidate.sub,
        "display_name": candidate.display_name,
        "languages": list(candidate.languages),
        "sworn": candidate.sworn,
        "key_version": candidate.key.key_version,
        "fingerprint": b64url(candidate.key.fingerprint),
        "fingerprint_display": display_fingerprint(candidate.key.fingerprint),
        "enc_pub": b64url(candidate.key.enc_pub),
        "sig_pub": b64url(candidate.key.sig_pub),
    }


def _assign_request(body: AssignBody) -> AssignRequest:
    try:
        wraps = tuple(
            AssignWrap(str(wrap.key_id), wrap.blob, from_b64url(wrap.signature))
            for wrap in body.wraps
        )
    except ValueError:
        raise refused(VerificationError("signature_invalid")) from None
    return AssignRequest(body.key_version, body.reviewer_sub, body.reviewer_key_version, wraps)


def _supervisor(claims: dict[str, Any]) -> bool:
    return SUPERVISE in permissions_of(claims)


@router.get("/{conversation_id}/reviewers")
async def reviewers(
    conversation_id: uuid.UUID,
    request: Request,
    context: TenantContext,
    claims: RecordingUser,
    service: Service,
) -> dict[str, Any]:
    try:
        found = await service.candidates(
            context.tenant_id,
            claims["sub"],
            str(conversation_id),
            correlation_id_from_request(request),
            supervisor=_supervisor(claims),
        )
    except VerificationError as error:
        raise refused(error) from None
    return {"reviewers": [_candidate_body(candidate) for candidate in found]}


@router.post(
    "/{conversation_id}/verifications",
    status_code=201,
    dependencies=[Depends(require_step_up)],
)
async def assign(
    conversation_id: uuid.UUID,
    body: AssignBody,
    request: Request,
    context: TenantContext,
    claims: RecordingUser,
    service: Service,
) -> dict[str, Any]:
    try:
        row = await service.assign(
            context.tenant_id,
            claims["sub"],
            str(conversation_id),
            _assign_request(body),
            correlation_id_from_request(request),
            supervisor=_supervisor(claims),
        )
    except VerificationError as error:
        raise refused(error) from None
    return record_body(row)
