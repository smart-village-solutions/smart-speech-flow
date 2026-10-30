"""An org admin's leaver list and marking (spec §9.8).

Marking needs step-up: it deletes a user's key blob and wraps. Both routes read
the Studio directory live and answer 503 rather than trust a failed or
implausible answer.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.crypto.encoding import b64url
from ..recording.crypto.transcript import display_fingerprint
from ..recording.leavers import KeyHolder, LeaverError, Leavers
from ..recording.permissions import coded, require_step_up
from ..studio_recording_directory_client import SUB_PATTERN
from ..studio_runtime_flow import correlation_id_from_request
from ..value_free_validation import ValueFreeValidationRoute
from .recording_ceremony import Admin, TenantContext

router = APIRouter(
    prefix="/api/admin/recording/leavers",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

_ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "directory_unavailable": (503, "DIRECTORY_UNAVAILABLE"),
    "still_in_directory": (409, "STILL_IN_DIRECTORY"),
    "already_left": (409, "ALREADY_LEFT"),
    "key_not_enrolled": (404, "KEY_NOT_ENROLLED"),
    "key_changed": (409, "KEY_CHANGED"),
    "ceremony_in_progress": (409, "CEREMONY_IN_PROGRESS"),
    "unavailable": (503, "RECORDING_UNAVAILABLE"),
}


def get_leavers(request: Request) -> Leavers:
    service: Leavers | None = getattr(optional_container(request), "recording_leavers", None)
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


LeaverService = Annotated[Leavers, Depends(get_leavers)]
Sub = Annotated[str, Path(pattern=SUB_PATTERN.pattern)]


class MarkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The version the list showed: a newer key is never retired in its place.
    key_version: int = Field(ge=1, le=10_000)


def _refused(error: LeaverError) -> Exception:
    status_code, code = _ANSWERS[error.code]
    return coded(status_code, code, "The leaver was refused")


def _candidate_body(holder: KeyHolder) -> dict[str, Any]:
    return {
        "sub": holder.sub,
        "key_version": holder.key_version,
        "fingerprint": b64url(holder.fingerprint),
        "fingerprint_display": display_fingerprint(holder.fingerprint),
        "enrolled_at": holder.enrolled_at.isoformat(),
        "conversations": holder.conversations,
        "last_conversation_at": (
            None if holder.last_conversation_at is None else holder.last_conversation_at.isoformat()
        ),
        "custodian": holder.custodian,
        "display_name": holder.display_name,
    }


@router.get("")
async def candidates(
    request: Request, context: TenantContext, claims: Admin, service: LeaverService
) -> dict[str, Any]:
    try:
        found = await service.candidates(context.tenant_id, correlation_id_from_request(request))
    except LeaverError as error:
        raise _refused(error) from None
    return {"candidates": [_candidate_body(holder) for holder in found]}


@router.post("/{sub}", dependencies=[Depends(require_step_up)])
async def mark(
    sub: Sub,
    body: MarkBody,
    request: Request,
    context: TenantContext,
    claims: Admin,
    service: LeaverService,
) -> dict[str, Any]:
    try:
        marked = await service.mark(
            context.tenant_id,
            claims["sub"],
            sub,
            body.key_version,
            correlation_id_from_request(request),
        )
    except LeaverError as error:
        raise _refused(error) from None
    return {
        "sub": marked.sub,
        "key_version": marked.key_version,
        "custodian": marked.custodian,
        "wraps_deleted": marked.wraps_deleted,
    }
