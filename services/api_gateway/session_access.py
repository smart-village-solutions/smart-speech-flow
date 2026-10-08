"""Fail-closed tenant authorization for conversation resources."""

from __future__ import annotations

import hmac
import logging
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from .auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user
from .dependencies import get_guest_grace_window, get_session_manager
from .log_safety import safe_closed_value
from .session_manager import TenantSessionManager
from .session_pseudonym import SessionPseudonymizer
from .tenant_context import StudioTenantContext, require_admin_ref, require_studio_tenant_context
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
_DENIAL_OUTCOMES = frozenset({"not_found", "owner_mismatch", "principal_scope_mismatch"})


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


async def require_admin_session_key(
    session_id: str,
    context: Annotated[
        StudioTenantContext,
        Depends(require_studio_tenant_context),
    ],
    sessions: Annotated[TenantSessionManager, Depends(get_session_manager)],
    owner_ref: Annotated[str, Depends(require_admin_ref)],
) -> TenantSessionKey:
    """Resolve an admin resource inside its tenant, for the admin who created it.

    A colleague's session, and one stored without an owner, answer exactly as an
    unknown id does, so the response never confirms that it exists (#476).
    """
    try:
        key = TenantSessionKey(context.tenant_id, session_id)
    except ValueError:
        raise _not_found() from None
    session = await sessions.get_session(key)
    if session is None:
        log_tenant_access_denied(key, outcome="not_found", pseudonymizer=sessions.pseudonymizer)
        raise _not_found()
    if not session.is_owned_by(owner_ref):
        log_tenant_access_denied(
            key, outcome="owner_mismatch", pseudonymizer=sessions.pseudonymizer
        )
        raise _not_found()
    return key


def _require_principal_scope(
    principal: dict[str, Any] | None, key: TenantSessionKey, sessions: TenantSessionManager
) -> None:
    """A supplied authenticated user must belong to the session's tenant."""
    if principal is None:
        return
    tenant_id = principal.get(VERIFIED_TENANT_ID_CLAIM)
    if not isinstance(tenant_id, str) or not hmac.compare_digest(tenant_id, key.tenant_id):
        log_tenant_access_denied(
            key, outcome="principal_scope_mismatch", pseudonymizer=sessions.pseudonymizer
        )
        raise _not_found()


async def require_customer_session_key(
    session_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
    sessions: Annotated[TenantSessionManager, Depends(get_session_manager)],
) -> TenantSessionKey:
    """Resolve a public capability and constrain any supplied authenticated user."""
    try:
        key = await sessions.resolve_customer_session(session_id)
    except ValueError:
        raise _not_found() from None
    if key is None:
        raise _not_found()
    _require_principal_scope(principal, key, sessions)
    return key


async def require_guest_session_key(
    session_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
    sessions: Annotated[TenantSessionManager, Depends(get_session_manager)],
    grace_window: Annotated[timedelta, Depends(get_guest_grace_window)],
) -> TenantSessionKey:
    """A live session's key, or an ended one's within the feedback grace period.

    The ended-conversation screen still shows the guest's texts and feedback
    form, while terminating the session revoked its join link. The key only
    selects the tenant's display content; it opens nothing of the conversation.
    """
    try:
        key = await sessions.resolve_customer_session(session_id)
        if key is None and grace_window > timedelta(0):
            key = await sessions.resolve_ended_session(session_id, within=grace_window)
    except ValueError:
        raise _not_found() from None
    if key is None:
        raise _not_found()
    _require_principal_scope(principal, key, sessions)
    return key
