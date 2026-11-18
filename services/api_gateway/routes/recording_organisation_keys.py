"""Studio's organisation key registry and manager-only actions."""

from typing import Any

from fastapi import Request, Response

from ..recording.lifecycle_models import (
    Activate,
    Identifier,
    OrganisationKey,
    PreparedKey,
    PrepareOrg,
    Registry,
    Subject,
)
from ..recording.permissions import TENANT_MANAGE, TRANSFER, permissions_of
from ..recording.preparations import error
from .recording_access_transfer import router as transfer_router
from .recording_lifecycle_auth import (
    Manager,
    Reader,
    Tenant,
    decoded,
    lifecycle_router,
    services,
    stored,
)

router = lifecycle_router("/v2")
router.include_router(transfer_router)


@router.get("/organisation-keys", response_model=Registry)
async def list_keys(request: Request, context: Tenant, claims: Reader) -> dict[str, Any]:
    org, transfers = services(request, claims)
    permission = TENANT_MANAGE if TENANT_MANAGE in permissions_of(claims) else TRANSFER
    await transfers.authorize(context.tenant_id, claims["sub"], permission)
    return await stored(org.list(context.tenant_id))


@router.post("/organisation-keys/preparations", response_model=PreparedKey)
async def prepare_key(
    body: PrepareOrg, request: Request, context: Tenant, claims: Manager
) -> dict[str, Any]:
    org, transfers = services(request, claims)
    await transfers.authorize(context.tenant_id, claims["sub"], TENANT_MANAGE)
    return await stored(
        org.prepare(
            context.tenant_id,
            claims["sub"],
            decoded(body.public_key, 65, "INVALID_KEY"),
            body.expected_active_key_id,
        )
    )


@router.post(
    "/organisation-keys/preparations/{pid}/activate",
    response_model=OrganisationKey,
)
async def activate_key(
    pid: Identifier, body: Activate, request: Request, context: Tenant, claims: Manager
) -> dict[str, Any]:
    org, transfers = services(request, claims)
    await transfers.authorize(context.tenant_id, claims["sub"], TENANT_MANAGE)
    if not body.saved_confirmation:
        raise error(422, "INVALID_PROOF")
    return await stored(
        org.activate(
            context.tenant_id, claims["sub"], pid, decoded(body.proof, 32, "INVALID_PROOF")
        )
    )


@router.delete("/organisation-keys/preparations/{pid}", status_code=204)
async def cancel_key(
    pid: Identifier, request: Request, context: Tenant, claims: Manager
) -> Response:
    org, transfers = services(request, claims)
    await transfers.authorize(context.tenant_id, claims["sub"], TENANT_MANAGE)
    await stored(org.cancel(context.tenant_id, claims["sub"], pid))
    return Response(status_code=204)


@router.delete("/users/{sub}/keys/{version}", status_code=204)
async def revoke_personal_key(
    sub: Subject, version: int, request: Request, context: Tenant, claims: Manager
) -> Response:
    org, transfers = services(request, claims)
    await transfers.authorize(context.tenant_id, claims["sub"], TENANT_MANAGE)
    await stored(org.revoke(context.tenant_id, claims["sub"], sub, version))
    return Response(status_code=204)
