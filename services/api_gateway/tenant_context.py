"""Trusted Studio tenant context for tenant-bound gateway operations."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from .auth import AuthenticatedPrincipal, require_ssf_user
from .auth_rejections import AuthRejectionReason, auth_correlation_id, record_auth_rejection

_SELECTOR_NAMES = frozenset(
    {
        "studio_instance_id",
        "studio_tenant_id",
        "studiotenantid",
        "tenant_id",
        "tenantid",
        "instanceid",
    }
)
_SELECTOR_HEADER_NAMES = frozenset({"x-studio-instance-id", "x-studio-tenant-id", "x-tenant-id"})


@dataclass(frozen=True)
class StudioTenantContext:
    """One trusted tenant identity represented with SSF terminology."""

    tenant_id: str
    authorization_revision: str


def studio_tenant_context_from_principal(
    principal: AuthenticatedPrincipal,
) -> StudioTenantContext:
    """Build a tenant context from the authenticated principal or fail closed.

    The principal's tenant is the directory entry whose realm issued the token;
    its tenant ID and revision were validated before the principal was built.
    """
    if principal.carries_legacy_tenant_claim:
        raise _invalid_tenant_claim()
    return StudioTenantContext(
        tenant_id=principal.tenant_id,
        authorization_revision=principal.authorization_revision,
    )


async def require_studio_tenant_context(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_ssf_user)],
) -> StudioTenantContext:
    """Take the tenant from the authenticated principal and reject request-side selectors."""
    if _request_has_tenant_selector(request, await _json_body(request)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant selectors are not accepted outside the bearer token",
        )
    if principal.carries_legacy_tenant_claim:
        record_auth_rejection(
            request,
            AuthRejectionReason.LEGACY_TENANT_CLAIM,
            correlation_id=auth_correlation_id(request),
            tenant_id=principal.tenant_id,
        )
    return studio_tenant_context_from_principal(principal)


def _request_has_tenant_selector(request: Request, body: object) -> bool:
    if _has_selector_name(request.path_params.keys()):
        return True
    if _has_selector_name(request.query_params.keys()):
        return True
    if _has_selector_name(request.cookies.keys()):
        return True
    if _SELECTOR_HEADER_NAMES.intersection(name.lower() for name in request.headers.keys()):
        return True
    return _contains_tenant_selector(body)


def _contains_tenant_selector(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if _has_selector_name(item.keys()):
                return True
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _has_selector_name(names: Iterable[object]) -> bool:
    return any(isinstance(name, str) and name.lower() in _SELECTOR_NAMES for name in names)


async def _json_body(request: Request) -> object:
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        return None
    try:
        return json.loads(await request.body())
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The JSON request body must be valid",
        ) from None


def _invalid_tenant_claim() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A single valid studio_tenant_id claim is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
