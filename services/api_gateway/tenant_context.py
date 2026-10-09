"""Trusted Studio tenant context for tenant-bound gateway operations."""

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Any, Mapping

from fastapi import Depends, HTTPException, Request, WebSocketException, status
from starlette.requests import HTTPConnection

from .auth import VERIFIED_TENANT_ID_CLAIM, require_ssf_user

_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
# Compared after _normalized_name, so every casing and "_"/"-" spelling is covered.
_SELECTOR_NAMES = frozenset({"studioinstanceid", "studiotenantid", "tenantid", "instanceid"})
_SELECTOR_HEADER_NAMES = frozenset({"xstudioinstanceid", "xstudiotenantid", "xtenantid"})


@dataclass(frozen=True)
class StudioTenantContext:
    """One trusted tenant identity represented with SSF terminology."""

    tenant_id: str
    authorization_revision: str | None = None


def studio_tenant_context_from_claims(
    claims: Mapping[str, Any],
) -> StudioTenantContext:
    """Build a tenant context only from the issuer-derived identity marker."""
    tenant_id = claims.get(VERIFIED_TENANT_ID_CLAIM)
    if not isinstance(tenant_id, str) or not _TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise _invalid_tenant_claim()

    return StudioTenantContext(tenant_id=tenant_id)


async def require_studio_tenant_context(
    request: Request,
    claims: Annotated[dict[str, Any], Depends(require_ssf_user)],
) -> StudioTenantContext:
    """Derive the tenant from the verified issuer and reject request-side selectors."""
    await reject_request_tenant_selectors(request)
    return studio_tenant_context_from_claims(claims)


def admin_ref(tenant_id: str, subject: str) -> str:
    """The admin who owns a session, without storing the account identifier.

    Comparing owners needs only equality, so a hash of the issuer-derived tenant
    and the verified subject is enough, and keeps the subject out of session
    records. It is a pseudonym, not a secret: anyone holding a subject can
    recompute it. It is unkeyed on purpose, because a key that changed with a
    restart would orphan every live session from its admin.
    """
    return hashlib.sha256(f"{tenant_id}\x1f{subject}".encode("utf-8")).hexdigest()[:32]


async def require_admin_ref(
    claims: Annotated[dict[str, Any], Depends(require_ssf_user)],
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
) -> str:
    """The requesting admin's owner reference; ``require_ssf_user`` guarantees ``sub``."""
    return admin_ref(context.tenant_id, claims["sub"])


async def reject_request_tenant_selectors(connection: HTTPConnection) -> None:
    """Reject caller-selected tenancy before HTTP or WebSocket operations."""
    body = await _json_body(connection) if isinstance(connection, Request) else None
    if _request_has_tenant_selector(connection, body):
        if connection.scope["type"] == "websocket":
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Tenant selectors are not accepted in requests",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant selectors are not accepted in requests",
        )


def _request_has_tenant_selector(request: HTTPConnection, body: object) -> bool:
    if _has_selector_name(request.path_params.keys()):
        return True
    if _has_selector_name(request.query_params.keys()):
        return True
    if _has_selector_name(request.cookies.keys()):
        return True
    if any(_normalized_name(name) in _SELECTOR_HEADER_NAMES for name in request.headers.keys()):
        return True
    return _contains_tenant_selector(_without_feedback_answers(body))


def _without_feedback_answers(body: object) -> object:
    """A feedback body without its `answers`, whose keys are Studio question ids.

    Studio's id pattern allows `tenantId` or `instanceId`, so scanning them would
    refuse every staff submission of a form that uses one. Only the top level is
    exempt; the body's own keys are still scanned.
    """
    if isinstance(body, dict) and "answers" in body:
        return {key: value for key, value in body.items() if key != "answers"}
    return body


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
    return any(
        isinstance(name, str) and _normalized_name(name) in _SELECTOR_NAMES for name in names
    )


def _normalized_name(name: str) -> str:
    return name.casefold().replace("_", "").replace("-", "")


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
        detail="A single verified tenant identity is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
