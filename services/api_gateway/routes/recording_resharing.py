"""Staff routes of a resharing (spec §9.7).

An org admin starts it, with step-up. A custodian dealer fetches its share and
the key that opens it, then deals through the ceremony's dealing route. The
ceremony device types in paper sheets and deals them here, without step-up: a
redirect would wipe the typed sheets, as for the paper confirmation.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.ceremony_model import CeremonyError, DealingSubmission
from ..recording.crypto.encoding import b64url, scalar_from_bytes
from ..recording.crypto.transcript import display_fingerprint
from ..recording.keys import KeyUnreadableError
from ..recording.permissions import (
    RECORDING_PERMISSIONS,
    TENANT_MANAGE,
    coded,
    require_permission,
    require_step_up,
)
from ..recording.repository import RecordingStorageUnavailable
from ..recording.resharing import ResharingService
from ..recording.resharing_model import ResharingStart
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute
from .recording_ceremony import POINT, SCALAR, ceremony_body, decoded, refused

router = APIRouter(
    prefix="/api/admin/recording/ceremony",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

Admin = Annotated[dict[str, Any], Depends(require_permission(TENANT_MANAGE))]
Staff = Annotated[
    dict[str, Any], Depends(require_permission(TENANT_MANAGE, *RECORDING_PERMISSIONS))
]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]


def get_resharing(request: Request) -> ResharingService:
    service: ResharingService | None = getattr(
        optional_container(request), "recording_resharing", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Resharings = Annotated[ResharingService, Depends(get_resharing)]


class ResharingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int = Field(ge=1, le=5)
    custodians: list[str] = Field(min_length=2, max_length=10)
    dealers: list[int] = Field(min_length=1, max_length=5)
    paper_device_pub: str | None = Field(default=None, min_length=POINT, max_length=POINT)
    holders_ceremony_id: uuid.UUID


class PaperDealingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dealer_index: int = Field(ge=1, le=15)
    commitments: list[str] = Field(min_length=1, max_length=5)
    c: str = Field(min_length=SCALAR, max_length=SCALAR)
    s: str = Field(min_length=SCALAR, max_length=SCALAR)
    subshares: dict[int, str] = Field(min_length=1, max_length=15)


@router.post(
    "/resharing", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_step_up)]
)
async def start_resharing(
    body: ResharingBody,
    request: Request,
    context: TenantContext,
    claims: Admin,
    service: Resharings,
) -> dict[str, Any]:
    device = (
        None
        if body.paper_device_pub is None
        else decoded(body.paper_device_pub, "INVALID_CEREMONY")
    )
    start = ResharingStart(
        body.k, tuple(body.custodians), tuple(body.dealers), device, str(body.holders_ceremony_id)
    )
    try:
        snapshot = await service.start(
            context.tenant_id, claims["sub"], start, correlation_id_from_request(request)
        )
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise refused(error) from None
    return ceremony_body(snapshot)


@router.get("/{ceremony_id}/dealer")
async def dealer(
    ceremony_id: uuid.UUID, context: TenantContext, claims: Staff, service: Resharings
) -> dict[str, Any]:
    try:
        found = await service.dealer(context.tenant_id, claims["sub"], str(ceremony_id))
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise refused(error) from None
    except KeyUnreadableError:
        raise coded(500, "KEY_UNREADABLE", "The stored key cannot be read") from None
    key = found.key
    return {
        "dealer_index": found.dealer_index,
        "encrypted_share": found.encrypted_share,
        "key": {
            "key_version": key.key_version,
            "enc_pub": b64url(key.enc_pub),
            "sig_pub": b64url(key.sig_pub),
            "blob": found.blob,
            "fingerprint": b64url(key.fingerprint),
            "fingerprint_display": display_fingerprint(key.fingerprint),
        },
    }


@router.post("/{ceremony_id}/paper-dealings", status_code=status.HTTP_201_CREATED)
async def paper_deal(
    ceremony_id: uuid.UUID,
    body: PaperDealingBody,
    context: TenantContext,
    claims: Admin,
    service: Resharings,
) -> dict[str, str]:
    submission = DealingSubmission(
        commitments=tuple(decoded(c, "INVALID_DEALING") for c in body.commitments),
        proof_c=scalar_from_bytes(decoded(body.c, "INVALID_DEALING")),
        proof_s=scalar_from_bytes(decoded(body.s, "INVALID_DEALING")),
        signature=None,
        subshares=body.subshares,
    )
    try:
        after = await service.paper_deal(
            context.tenant_id, claims["sub"], str(ceremony_id), body.dealer_index, submission
        )
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise refused(error) from None
    return {"status": "confirming" if after.all_dealt() else "dealing"}
