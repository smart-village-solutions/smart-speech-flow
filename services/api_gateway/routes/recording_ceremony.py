"""Staff routes of the recovery-key ceremony (spec §9.2).

The tenant administrator starts a ceremony and, when paper shares are wanted,
runs the ceremony device; custodians deal and confirm. Starting, dealing and
confirming need a fresh MFA login. Aborting does not, so that a custodian
whose browser finds a fault can always stop the ceremony; the paper
confirmation does not either, because a step-up redirect would wipe the
device key it depends on. Both are audited.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.ceremony import CeremonyService, CeremonyState, StartRequest
from ..recording.ceremony_model import (
    CeremonyError,
    CeremonySnapshot,
    DealingSubmission,
    RecoveryKeyRecord,
)
from ..recording.crypto.encoding import b64url, from_b64url, scalar_from_bytes
from ..recording.crypto.transcript import display_fingerprint
from ..recording.permissions import (
    CUSTODIAN,
    TENANT_MANAGE,
    coded,
    require_permission,
    require_step_up,
)
from ..recording.repository import RecordingStorageUnavailable
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/admin/recording/ceremony",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

Admin = Annotated[dict[str, Any], Depends(require_permission(TENANT_MANAGE))]
Custodian = Annotated[dict[str, Any], Depends(require_permission(CUSTODIAN))]
Participant = Annotated[dict[str, Any], Depends(require_permission(TENANT_MANAGE, CUSTODIAN))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
StepUp = [Depends(require_step_up)]
_POINT = 87  # a 65-byte point in unpadded base64url
_SCALAR = 43  # 32 bytes
_SIGNATURE = 86  # 64 bytes


def get_ceremony(request: Request) -> CeremonyService:
    service: CeremonyService | None = getattr(
        optional_container(request), "recording_ceremony", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Ceremonies = Annotated[CeremonyService, Depends(get_ceremony)]


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int = Field(ge=1, le=5)
    custodians: list[str] = Field(min_length=2, max_length=10)
    paper_device_pub: str | None = Field(default=None, min_length=_POINT, max_length=_POINT)


class DealingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commitments: list[str] = Field(min_length=1, max_length=5)
    c: str = Field(min_length=_SCALAR, max_length=_SCALAR)
    s: str = Field(min_length=_SCALAR, max_length=_SCALAR)
    signature: str = Field(min_length=_SIGNATURE, max_length=_SIGNATURE)
    subshares: dict[int, str] = Field(min_length=1, max_length=15)


class ConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_signature: str = Field(min_length=_SIGNATURE, max_length=_SIGNATURE)
    encrypted_share: str = Field(min_length=1, max_length=1024)


class PaperConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_hash: str = Field(min_length=_SCALAR, max_length=_SCALAR)


class AbortBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=40)


def _refused(error: Exception) -> Exception:
    if isinstance(error, CeremonyError):
        return coded(error.status, error.code, error.message)
    return coded(503, "RECORDING_UNAVAILABLE", "Recording storage unavailable")


def _decoded(text: str, code: str) -> bytes:
    try:
        return from_b64url(text)
    except ValueError:
        raise coded(422, code, "A value is not unpadded base64url") from None


def _key_body(key: RecoveryKeyRecord) -> dict[str, Any]:
    return {
        "key_id": key.key_id,
        "recovery_public_key": b64url(key.recovery_public_key),
        "k": key.k,
        "n": key.n,
        "mode": key.mode,
        "transcript_hash": b64url(key.transcript_hash),
        "transcript_display": display_fingerprint(key.transcript_hash),
        "activated_at": key.activated_at.isoformat(),
    }


def _ceremony_body(snapshot: CeremonySnapshot) -> dict[str, Any]:
    ceremony = snapshot.ceremony
    transcript = ceremony.transcript_hash
    return {
        "ceremony_id": ceremony.ceremony_id,
        "k": ceremony.k,
        "status": ceremony.status,
        "started_by": ceremony.started_by,
        "started_at": ceremony.started_at.isoformat(),
        "expires_at": ceremony.expires_at.isoformat(),
        "gateway_keys": [
            {"key_id": key_id, "public_key": b64url(public)}
            for key_id, public in ceremony.gateway_keys
        ],
        "participants": [
            {
                "holder_index": p.holder_index,
                "holder_ref": p.holder_ref,
                "kind": p.kind,
                "display_name": p.display_name,
                "enc_pub": b64url(p.enc_pub),
                "sig_pub": None if p.sig_pub is None else b64url(p.sig_pub),
                "fingerprint": b64url(p.fingerprint),
            }
            for p in snapshot.participants
        ],
        "dealings": [
            {
                "dealer_index": d.dealer_index,
                "commitments": [b64url(c) for c in d.commitments],
                "c": b64url(d.proof_c.to_bytes(32, "big")),
                "s": b64url(d.proof_s.to_bytes(32, "big")),
                "signature": b64url(d.signature),
            }
            for d in snapshot.dealings
        ],
        "confirmed": [c.holder_index for c in snapshot.confirmations],
        "paper_confirmed": ceremony.paper_confirmed_at is not None,
        "transcript_hash": None if transcript is None else b64url(transcript),
    }


def _state_body(state: CeremonyState) -> dict[str, Any]:
    return {
        "recovery_key": None if state.recovery_key is None else _key_body(state.recovery_key),
        "ceremony": None if state.ceremony is None else _ceremony_body(state.ceremony),
        "last_failed": (
            None
            if state.last_failed is None
            else {
                "ceremony_id": state.last_failed.ceremony_id,
                "reason": state.last_failed.reason,
                "ended_at": state.last_failed.ended_at.isoformat(),
            }
        ),
    }


@router.get("")
async def ceremony_state(
    context: TenantContext, claims: Participant, service: Ceremonies
) -> dict[str, Any]:
    try:
        return _state_body(await service.state(context.tenant_id))
    except RecordingStorageUnavailable as error:
        raise _refused(error) from None


@router.get("/candidates")
async def candidates(
    request: Request, context: TenantContext, claims: Admin, service: Ceremonies
) -> dict[str, Any]:
    try:
        found = await service.candidates(context.tenant_id, correlation_id_from_request(request))
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return {
        "candidates": [
            {
                "sub": c.sub,
                "display_name": c.display_name,
                "fingerprint_display": (
                    None if c.fingerprint is None else display_fingerprint(c.fingerprint)
                ),
            }
            for c in found
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=StepUp)
async def start(
    body: StartBody,
    request: Request,
    context: TenantContext,
    claims: Admin,
    service: Ceremonies,
) -> dict[str, Any]:
    device = (
        None
        if body.paper_device_pub is None
        else _decoded(body.paper_device_pub, "INVALID_CEREMONY")
    )
    start_request = StartRequest(body.k, tuple(body.custodians), device)
    try:
        snapshot = await service.start(
            context.tenant_id, claims["sub"], start_request, correlation_id_from_request(request)
        )
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return _ceremony_body(snapshot)


@router.post("/{ceremony_id}/dealings", status_code=status.HTTP_201_CREATED, dependencies=StepUp)
async def deal(
    ceremony_id: uuid.UUID,
    body: DealingBody,
    context: TenantContext,
    claims: Custodian,
    service: Ceremonies,
) -> dict[str, str]:
    submission = DealingSubmission(
        commitments=tuple(_decoded(c, "INVALID_DEALING") for c in body.commitments),
        proof_c=scalar_from_bytes(_decoded(body.c, "INVALID_DEALING")),
        proof_s=scalar_from_bytes(_decoded(body.s, "INVALID_DEALING")),
        signature=_decoded(body.signature, "INVALID_DEALING"),
        subshares=body.subshares,
    )
    try:
        after = await service.deal(context.tenant_id, claims["sub"], str(ceremony_id), submission)
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return {"status": "confirming" if after.all_dealt() else "dealing"}


@router.get("/{ceremony_id}/subshares")
async def subshares(
    ceremony_id: uuid.UUID, context: TenantContext, claims: Participant, service: Ceremonies
) -> dict[str, dict[str, dict[str, str]]]:
    try:
        received = await service.subshares(context.tenant_id, claims["sub"], str(ceremony_id))
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return {
        "subshares": {
            str(index): {str(dealer): sealed for dealer, sealed in by_dealer.items()}
            for index, by_dealer in received.items()
        }
    }


@router.post(
    "/{ceremony_id}/confirmations", status_code=status.HTTP_201_CREATED, dependencies=StepUp
)
async def confirm(
    ceremony_id: uuid.UUID,
    body: ConfirmationBody,
    context: TenantContext,
    claims: Custodian,
    service: Ceremonies,
) -> dict[str, str]:
    signature = _decoded(body.transcript_signature, "INVALID_CONFIRMATION")
    try:
        result = await service.confirm(
            context.tenant_id, claims["sub"], str(ceremony_id), signature, body.encrypted_share
        )
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return {"status": result}


@router.post("/{ceremony_id}/paper-confirmation", status_code=status.HTTP_201_CREATED)
async def confirm_paper(
    ceremony_id: uuid.UUID,
    body: PaperConfirmationBody,
    context: TenantContext,
    claims: Admin,
    service: Ceremonies,
) -> dict[str, str]:
    transcript = _decoded(body.transcript_hash, "TRANSCRIPT_MISMATCH")
    try:
        result = await service.confirm_paper(
            context.tenant_id, claims["sub"], str(ceremony_id), transcript
        )
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
    return {"status": result}


@router.post("/{ceremony_id}/abort", status_code=status.HTTP_204_NO_CONTENT)
async def abort(
    ceremony_id: uuid.UUID,
    body: AbortBody,
    context: TenantContext,
    claims: Participant,
    service: Ceremonies,
) -> None:
    try:
        await service.abort(context.tenant_id, claims["sub"], str(ceremony_id), body.reason)
    except (CeremonyError, RecordingStorageUnavailable) as error:
        raise _refused(error) from None
