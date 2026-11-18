"""Effective recording permissions and verified email from authenticated user tokens."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final

from fastapi import Depends, HTTPException, status

from ..auth import require_ssf_user

PERMISSIONS_CLAIM: Final[str] = "ssf_permissions"
REQUEST: Final[str] = "ssf.recording.request"
REVIEW: Final[str] = "ssf.recording.review"
REVIEW_SWORN: Final[str] = "ssf.recording.review.sworn"
# What a verification decision snapshots (spec A.3a).
REVIEW_PERMISSIONS: Final[tuple[str, ...]] = (REVIEW, REVIEW_SWORN)
TRANSFER: Final[str] = "ssf.recording.access.transfer"
SUPERVISE: Final[str] = "ssf.recording.supervise"
CUSTODIAN: Final[str] = "ssf.recording.recovery.custodian"
# The tenant administrator's existing Studio permission (keycloak.ts reads it too).
TENANT_MANAGE: Final[str] = "ssf.configuration.tenant.manage"
RECORDING_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {REQUEST, REVIEW, REVIEW_SWORN, SUPERVISE, CUSTODIAN}
)

Claims = dict[str, Any]
MAX_EMAIL_CHARACTERS: Final[int] = 254


def coded(status_code: int, code: str, message: str) -> HTTPException:
    """The gateway's coded envelope, read by the frontend as `detail.error_code`."""
    return HTTPException(status_code=status_code, detail={"error_code": code, "message": message})


def permissions_of(claims: Claims) -> frozenset[str]:
    """A malformed claim grants nothing rather than failing the request."""
    raw = claims.get(PERMISSIONS_CLAIM)
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, str))


def require_permission(*accepted: str) -> Callable[..., Awaitable[Claims]]:
    """A dependency admitting a caller holding any one of `accepted`."""

    async def dependency(claims: Annotated[Claims, Depends(require_ssf_user)]) -> Claims:
        if permissions_of(claims).isdisjoint(accepted):
            raise coded(status.HTTP_403_FORBIDDEN, "PERMISSION_REQUIRED", "Permission missing")
        return claims

    return dependency


def verified_email(claims: Claims) -> str | None:
    """The token's address when Keycloak marked it verified; None otherwise (§9.9)."""
    email = claims.get("email")
    if claims.get("email_verified") is not True or not isinstance(email, str):
        return None
    return email if 0 < len(email) <= MAX_EMAIL_CHARACTERS else None
