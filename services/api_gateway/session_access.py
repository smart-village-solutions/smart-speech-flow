"""Fail-closed tenant authorization for conversation resources."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from .auth import optional_ssf_user
from .log_safety import safe_closed_value
from .session_manager import session_manager
from .session_pseudonym import session_ref
from .tenant_context import StudioTenantContext, require_studio_tenant_context
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
_DENIAL_OUTCOMES = frozenset({"not_found", "principal_scope_mismatch"})


def log_tenant_access_denied(key: TenantSessionKey, *, outcome: str) -> None:
    """Emit only bounded pseudonyms and a fixed-cardinality outcome."""
    safe_outcome = safe_closed_value(outcome, _DENIAL_OUTCOMES)
    fields = {
        "tenant_ref": key.tenant_ref,
        "session_ref": session_ref(key.session_id),
        "outcome": safe_outcome,
    }
    logger.info(
        "tenant_session_access_denied tenant_ref=%s session_ref=%s outcome=%s",
        fields["tenant_ref"],
        fields["session_ref"],
        fields["outcome"],
        extra=fields,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found",
    )


def require_admin_session_key(
    session_id: str,
    context: Annotated[
        StudioTenantContext,
        Depends(require_studio_tenant_context),
    ],
) -> TenantSessionKey:
    """Resolve an admin resource strictly inside its authenticated tenant."""
    try:
        key = TenantSessionKey(context.tenant_id, session_id)
    except ValueError:
        raise _not_found() from None
    if session_manager.get_session(key) is None:
        log_tenant_access_denied(key, outcome="not_found")
        raise _not_found()
    return key


def require_customer_session_key(
    session_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
) -> TenantSessionKey:
    """Resolve a public capability and constrain any supplied authenticated user."""
    try:
        key = session_manager.resolve_customer_session(session_id)
    except ValueError:
        raise _not_found() from None
    if key is None:
        raise _not_found()
    if principal is not None:
        tenant_id = principal.get("studio_tenant_id")
        if not isinstance(tenant_id, str) or not hmac.compare_digest(
            tenant_id, key.tenant_id
        ):
            log_tenant_access_denied(key, outcome="principal_scope_mismatch")
            raise _not_found()
    return key
