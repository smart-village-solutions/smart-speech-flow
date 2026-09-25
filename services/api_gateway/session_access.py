"""Fail-closed tenant authorization for conversation resources."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from .auth import optional_ssf_user
from .dependencies import get_session_manager
from .log_safety import safe_closed_value
from .session_manager import TenantSessionManager
from .session_pseudonym import SessionPseudonymizer
from .tenant_context import StudioTenantContext, require_studio_tenant_context
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
_DENIAL_OUTCOMES = frozenset({"not_found", "principal_scope_mismatch"})


def log_tenant_access_denied(
    key: TenantSessionKey, *, outcome: str, pseudonymizer: SessionPseudonymizer
) -> None:
    """Emit only bounded pseudonyms and a fixed-cardinality outcome."""
    safe_outcome = safe_closed_value(outcome, _DENIAL_OUTCOMES)
    fields = {
        "tenant_ref": key.tenant_ref,
        "session_ref": pseudonymizer.reference(key.session_id),
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
    sessions: Annotated[TenantSessionManager, Depends(get_session_manager)],
) -> TenantSessionKey:
    """Resolve an admin resource strictly inside its authenticated tenant."""
    try:
        key = TenantSessionKey(context.tenant_id, session_id)
    except ValueError:
        raise _not_found() from None
    if sessions.get_session(key) is None:
        log_tenant_access_denied(key, outcome="not_found", pseudonymizer=sessions.pseudonymizer)
        raise _not_found()
    return key


def require_customer_session_key(
    session_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
    sessions: Annotated[TenantSessionManager, Depends(get_session_manager)],
) -> TenantSessionKey:
    """Resolve a public capability and constrain any supplied authenticated user."""
    try:
        key = sessions.resolve_customer_session(session_id)
    except ValueError:
        raise _not_found() from None
    if key is None:
        raise _not_found()
    if principal is not None:
        tenant_id = principal.get("studio_tenant_id")
        if not isinstance(tenant_id, str) or not hmac.compare_digest(tenant_id, key.tenant_id):
            log_tenant_access_denied(
                key, outcome="principal_scope_mismatch", pseudonymizer=sessions.pseudonymizer
            )
            raise _not_found()
    return key
