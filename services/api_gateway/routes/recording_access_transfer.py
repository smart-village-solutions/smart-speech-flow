"""Studio transfer candidates, current recipient keys and exact-scope grants."""

from typing import Annotated, Any

from fastapi import Query, Request

from ..recording.access_transfer import strict_wrap
from ..recording.lifecycle_models import (
    Candidates,
    Commit,
    Identifier,
    PreparedTransfer,
    PrepareTransfer,
    Subject,
    TargetKey,
    TransferReceipt,
)
from ..recording.preparations import error
from .recording_lifecycle_auth import (
    Tenant,
    Transfer,
    decoded,
    lifecycle_router,
    services,
    stored,
)

router = lifecycle_router()


@router.get("/access-transfer/candidates", response_model=Candidates)
async def candidates(
    employee_sub: Annotated[str, Query(alias="employeeSub", min_length=1, max_length=255)],
    request: Request,
    context: Tenant,
    claims: Transfer,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> dict[str, Any]:
    _, service = services(request, claims)
    return await stored(service.candidates(context.tenant_id, claims["sub"], employee_sub, cursor))


@router.get("/access-transfer/targets/{sub}", response_model=TargetKey)
async def transfer_target(
    sub: Subject, request: Request, context: Tenant, claims: Transfer
) -> dict[str, Any]:
    _, service = services(request, claims)
    return await stored(service.target(context.tenant_id, claims["sub"], sub))


@router.post("/access-transfer/preparations", response_model=PreparedTransfer)
async def prepare_transfer(
    body: PrepareTransfer, request: Request, context: Tenant, claims: Transfer
) -> dict[str, Any]:
    _, service = services(request, claims)
    return await stored(
        service.prepare(
            context.tenant_id,
            claims["sub"],
            body.conversation_ids,
            body.organisation_key_id,
            body.target_user_sub,
            body.expected_target_key_version,
            body.expected_target_fingerprint,
            body.reason,
        )
    )


@router.post(
    "/access-transfer/preparations/{pid}/commit",
    response_model=TransferReceipt,
)
async def transfer_commit(
    pid: Identifier, body: Commit, request: Request, context: Tenant, claims: Transfer
) -> dict[str, Any]:
    _, service = services(request, claims)
    wraps = {
        (w.conversation_id, w.key_id): strict_wrap(w.envelope.model_dump(by_alias=True))
        for w in body.wraps
    }
    if len(wraps) != len(body.wraps):
        raise error(409, "SCOPE_CHANGED")
    return await stored(
        service.commit(
            context.tenant_id, claims["sub"], pid, decoded(body.proof, 32, "INVALID_PROOF"), wraps
        )
    )
