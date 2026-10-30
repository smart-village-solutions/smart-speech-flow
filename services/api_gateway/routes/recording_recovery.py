"""Recovery through custodian approval (spec §9.5, §9.6).

A supervisor (access) or an employee for their own conversations (key
recovery) files a signed request; custodians approve it with signed partials
sealed for the requester; the requester's browser combines them and stores its
own wraps. The service checks shapes and signatures; nothing here ever sees a
share, a partial's plaintext or a conversation key.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from ..dependencies import optional_container
from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.permissions import (
    CUSTODIAN,
    RECORDING_PERMISSIONS,
    SUPERVISE,
    coded,
    permissions_of,
    require_permission,
    require_step_up,
)
from ..recording.recovery_requests import ApprovalView, RecoveryRequestError, RecoveryRequests
from ..recording.recovery_requests_model import (
    MAX_BODY_KEYS,
    Candidate,
    NewWrap,
    Progress,
    RequestRow,
    ServedPartials,
)
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/admin/recording/recovery",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

Supervisor = Annotated[dict[str, Any], Depends(require_permission(SUPERVISE))]
# Any key holder: an access request re-checks `supervise` under its lock (§9.6).
Requester = Annotated[dict[str, Any], Depends(require_permission(*RECORDING_PERMISSIONS))]
Custodian = Annotated[dict[str, Any], Depends(require_permission(CUSTODIAN))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
StepUp = [Depends(require_step_up)]
_SIGNATURE = 86  # 64 bytes in unpadded base64url
_SEALED = 1024

_ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "not_found": (404, "REQUEST_NOT_FOUND"),
    "conversation_not_found": (404, "CONVERSATION_NOT_FOUND"),
    "recovery_key_missing": (404, "RECOVERY_KEY_MISSING"),
    "requester_cannot_approve": (403, "REQUESTER_CANNOT_APPROVE"),
    "closed": (409, "REQUEST_CLOSED"),
    "already_decided": (409, "ALREADY_DECIDED"),
    "not_enough_approvals": (409, "NOT_ENOUGH_APPROVALS"),
    "request_exists": (409, "REQUEST_EXISTS"),
    "already_accessible": (409, "ALREADY_ACCESSIBLE"),
    "key_not_enrolled": (409, "KEY_NOT_ENROLLED"),
    "key_changed": (409, "KEY_CHANGED"),
    "share_stale": (409, "SHARE_STALE"),
    "forbidden": (403, "PERMISSION_REQUIRED"),
    "signature_invalid": (422, "SIGNATURE_INVALID"),
    "bad_partial": (422, "BAD_PARTIAL"),
    "scope_not_covered": (422, "SCOPE_NOT_COVERED"),
    "scope_too_large": (422, "SCOPE_TOO_LARGE"),
    "bad_stage": (422, "BAD_STAGE"),
    "unavailable": (503, "RECORDING_UNAVAILABLE"),
}


def get_recovery_requests(request: Request) -> RecoveryRequests:
    service: RecoveryRequests | None = getattr(
        optional_container(request), "recording_recovery_requests", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Requests = Annotated[RecoveryRequests, Depends(get_recovery_requests)]
Signature = Annotated[str, Field(min_length=_SIGNATURE, max_length=_SIGNATURE)]
SealedText = Annotated[str, Field(min_length=1, max_length=_SEALED)]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]


class FileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    kind: Literal["access", "key_recovery"] = "access"
    reason: Reason
    # The per-kind limit is the repository's; this only bounds the body.
    conversation_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BODY_KEYS)
    signature: Signature

    @field_validator("conversation_ids")
    @classmethod
    def unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("conversation IDs must be unique")
        return value


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partials: dict[uuid.UUID, SealedText] = Field(min_length=1, max_length=MAX_BODY_KEYS)
    signature: Signature


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class RejectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holder_index: int = Field(ge=1, le=15)
    attempt: int = Field(ge=1, le=100)
    fault: Literal["partial_unreadable", "proof_invalid"]


class IntegrityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["trust", "wrap_signature", "approval_signature", "partial_hash", "wrap_damaged"]
    # Names one recovery wrap the requester could not use: it leaves their scope (§9.6).
    key_id: uuid.UUID | None = None


class WrapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID
    key_id: uuid.UUID
    blob: SealedText
    signature: Signature


class WrapsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Empty when every key of the scope was reported unrecoverable.
    wraps: list[WrapItem] = Field(max_length=MAX_BODY_KEYS)


def _answer(error: RecoveryRequestError, *, not_found: str = "not_found") -> HTTPException:
    code = not_found if error.code == "not_found" else error.code
    status, answer = _ANSWERS.get(code, (503, "RECORDING_UNAVAILABLE"))
    return HTTPException(
        status_code=status,
        detail={"error_code": answer, "message": "The recovery request was refused"},
    )


def _bytes(text: str) -> bytes:
    try:
        return from_b64url(text)
    except ValueError:
        raise _answer(RecoveryRequestError("signature_invalid")) from None


def _may_supervise(claims: dict[str, Any]) -> bool:
    return SUPERVISE in permissions_of(claims)


def _summary(row: RequestRow, conversations: int) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "kind": row.kind,
        "requester_sub": row.requester_sub,
        "status": row.status,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "conversations": conversations,
    }


def _progress_body(progress: Progress, names: Mapping[str, str]) -> dict[str, Any]:
    return _summary(progress.request, progress.conversations) | {
        "k": progress.k,
        "decisions": [
            {
                "holder_index": d.holder_index,
                "attempt": d.attempt,
                "custodian_sub": d.custodian_sub,
                "custodian_name": names.get(d.custodian_sub),
                "decision": d.decision,
                "reason": d.reason,
                "decided_at": d.decided_at.isoformat(),
                "rejected": d.rejected,
            }
            for d in progress.decisions
        ],
        "scope": [
            {"conversation_id": k.conversation_id, "key_id": k.key_id} for k in progress.remaining
        ],
    }


def _partials_body(served: ServedPartials) -> dict[str, Any]:
    return {
        "wraps": [
            {
                "conversation_id": w.conversation_id,
                "key_id": w.key_id,
                "blob": w.blob,
                "creator_ref": w.creator_ref,
                "signature": b64url(w.creator_signature),
            }
            for w in served.wraps
        ],
        "approvals": [
            {
                "holder_index": a.holder_index,
                "attempt": a.attempt,
                "signed_partials": [
                    {"key_id": key_id, "hash": b64url(digest)}
                    for key_id, digest in a.signed_partials
                ],
                "signature": b64url(a.approval_signature),
                "partials": dict(a.blobs),
            }
            for a in served.approvals
        ],
    }


def _approval_body(view: ApprovalView) -> dict[str, Any]:
    request = view.request
    return {
        "request_id": request.request_id,
        "kind": request.kind,
        "recovery_key_id": request.recovery_key_id,
        "requester_sub": request.requester_sub,
        "requester_name": view.requester_name,
        "requester_enc_pub": b64url(view.requester_enc_pub),
        "requester_sig_pub": b64url(view.requester_sig_pub),
        "reason": request.reason,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "request_signature": b64url(request.request_signature),
        "signed_scope": [
            {"conversation_id": k.conversation_id, "key_id": k.key_id} for k in view.signed_scope
        ],
        # R and the gateway's signature only: never a wrap's nonce or ciphertext (§9.1).
        "keys": [
            {
                "conversation_id": k.conversation_id,
                "key_id": k.key_id,
                "employee_sub": k.employee_sub,
                "employee_name": k.employee_name,
                "started_at": k.started_at.isoformat(),
                "ended_at": k.ended_at.isoformat(),
                "ephemeral": b64url(k.ephemeral),
                "signer_key_id": k.creator_ref,
                "signature": b64url(k.creator_signature),
            }
            for k in view.keys
        ],
        "holder_index": view.holder_index,
        "attempt": view.attempt,
        "encrypted_share": view.encrypted_share,
    }


@router.get("/employees")
async def employees(
    request: Request, context: TenantContext, claims: Supervisor, service: Requests
) -> dict[str, Any]:
    try:
        found = await service.employees(context.tenant_id, correlation_id_from_request(request))
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {"employees": [{"sub": sub, "display_name": name} for sub, name in found]}


@router.get("/candidates")
async def candidates(
    context: TenantContext,
    claims: Supervisor,
    service: Requests,
    employee: Annotated[str, Query(min_length=1, max_length=255)],
    start: Annotated[AwareDatetime, Query(alias="from")],
    end: Annotated[AwareDatetime, Query(alias="to")],
) -> dict[str, Any]:
    if end <= start:
        raise coded(422, "BAD_RANGE", "The range must end after it starts")
    try:
        found = await service.candidates(context.tenant_id, claims["sub"], employee, start, end)
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {"conversations": [_candidate_body(c) for c in found]}


def _candidate_body(c: Candidate) -> dict[str, Any]:
    return {
        "conversation_id": c.conversation_id,
        "started_at": c.started_at.isoformat(),
        "ended_at": c.ended_at.isoformat(),
        "retention_until": c.retention_until.isoformat(),
        "legal_hold": c.legal_hold,
        "incomplete": c.incomplete,
        "key_ids": list(c.key_ids),
    }


@router.get("/own/candidates")
async def own_candidates(
    context: TenantContext, claims: Requester, service: Requests
) -> dict[str, Any]:
    """The caller's next key-recovery batch, and what remains after it (§9.6)."""
    try:
        batch, conversations, keys = await service.own_candidates(context.tenant_id, claims["sub"])
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {
        "conversations": [_candidate_body(c) for c in batch],
        "remaining": {"conversations": conversations, "keys": keys},
    }


@router.post("/requests", status_code=201, dependencies=StepUp)
async def file_request(
    body: FileBody, context: TenantContext, claims: Requester, service: Requests
) -> dict[str, Any]:
    if body.kind == "access" and not _may_supervise(claims):
        raise coded(403, "PERMISSION_REQUIRED", "Permission missing")
    signature = _bytes(body.signature)
    try:
        scope = await service.file(
            context.tenant_id,
            claims["sub"],
            str(body.request_id),
            body.kind,
            body.reason,
            tuple(str(c) for c in body.conversation_ids),
            signature,
        )
    except RecoveryRequestError as error:
        raise _answer(error, not_found="conversation_not_found") from None
    return {
        "request_id": str(body.request_id),
        "scope": [{"conversation_id": k.conversation_id, "key_id": k.key_id} for k in scope],
    }


@router.get("/requests")
async def own_requests(
    context: TenantContext,
    claims: Requester,
    service: Requests,
    kind: Literal["access", "key_recovery"] | None = None,
) -> dict[str, Any]:
    try:
        rows = await service.own_requests(context.tenant_id, claims["sub"], kind)
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {"requests": [_summary(row, count) for row, count in rows]}


@router.get("/requests/{request_id}")
async def progress(
    request_id: uuid.UUID,
    request: Request,
    context: TenantContext,
    claims: Requester,
    service: Requests,
) -> dict[str, Any]:
    try:
        found, names = await service.progress(
            context.tenant_id,
            claims["sub"],
            str(request_id),
            correlation_id_from_request(request),
            may_supervise=_may_supervise(claims),
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return _progress_body(found, names)


@router.get("/requests/{request_id}/partials")
async def partials(
    request_id: uuid.UUID, context: TenantContext, claims: Requester, service: Requests
) -> dict[str, Any]:
    try:
        served = await service.partials(
            context.tenant_id, claims["sub"], str(request_id), may_supervise=_may_supervise(claims)
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return _partials_body(served)


@router.post("/requests/{request_id}/rejections", status_code=204)
async def reject(
    request_id: uuid.UUID,
    body: RejectionBody,
    context: TenantContext,
    claims: Requester,
    service: Requests,
) -> Response:
    try:
        await service.reject(
            context.tenant_id,
            claims["sub"],
            str(request_id),
            (body.holder_index, body.attempt),
            body.fault,
            may_supervise=_may_supervise(claims),
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return Response(status_code=204)


@router.post("/requests/{request_id}/integrity-failures", status_code=204)
async def integrity_failure(
    request_id: uuid.UUID,
    body: IntegrityBody,
    context: TenantContext,
    claims: Requester,
    service: Requests,
) -> Response:
    try:
        await service.report(
            context.tenant_id,
            claims["sub"],
            str(request_id),
            body.stage,
            may_supervise=_may_supervise(claims),
            key_id=None if body.key_id is None else str(body.key_id),
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return Response(status_code=204)


@router.post("/requests/{request_id}/wraps")
async def store_wraps(
    request_id: uuid.UUID,
    body: WrapsBody,
    context: TenantContext,
    claims: Requester,
    service: Requests,
) -> dict[str, Any]:
    wraps = [
        NewWrap(str(w.conversation_id), str(w.key_id), w.blob, _bytes(w.signature))
        for w in body.wraps
    ]
    try:
        dropped = await service.store(
            context.tenant_id,
            claims["sub"],
            str(request_id),
            wraps,
            may_supervise=_may_supervise(claims),
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {"dropped": list(dropped)}


@router.post("/requests/{request_id}/cancel", status_code=204)
async def cancel(
    request_id: uuid.UUID, context: TenantContext, claims: Requester, service: Requests
) -> Response:
    try:
        await service.cancel(context.tenant_id, claims["sub"], str(request_id))
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return Response(status_code=204)


@router.get("/approvals")
async def approvals(context: TenantContext, claims: Custodian, service: Requests) -> dict[str, Any]:
    try:
        rows, stale = await service.approvals(context.tenant_id, claims["sub"])
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return {"requests": [_summary(row, count) for row, count in rows], "share_stale": stale}


@router.get("/approvals/{request_id}")
async def approval(
    request_id: uuid.UUID,
    request: Request,
    context: TenantContext,
    claims: Custodian,
    service: Requests,
) -> dict[str, Any]:
    try:
        view = await service.approval(
            context.tenant_id, claims["sub"], str(request_id), correlation_id_from_request(request)
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return _approval_body(view)


@router.post("/approvals/{request_id}", status_code=201, dependencies=StepUp)
async def approve(
    request_id: uuid.UUID,
    body: ApproveBody,
    context: TenantContext,
    claims: Custodian,
    service: Requests,
) -> Response:
    signature = _bytes(body.signature)
    try:
        await service.approve(
            context.tenant_id,
            claims["sub"],
            str(request_id),
            {str(key_id): blob for key_id, blob in body.partials.items()},
            signature,
        )
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return Response(status_code=201)


@router.post("/approvals/{request_id}/decline", status_code=204, dependencies=StepUp)
async def decline(
    request_id: uuid.UUID,
    body: ReasonBody,
    context: TenantContext,
    claims: Custodian,
    service: Requests,
) -> Response:
    try:
        await service.decline(context.tenant_id, claims["sub"], str(request_id), body.reason)
    except RecoveryRequestError as error:
        raise _answer(error) from None
    return Response(status_code=204)
