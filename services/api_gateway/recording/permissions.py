"""Recording permissions from the Studio `ssf_permissions` claim, and step-up (spec §14, §3).

Studio is authoritative for administrative permissions, and the gateway
already verifies the token they arrive in. No permission grants content
access by itself; only a key wrap does. Step-up is a fresh multi-factor
login: the realm maps it to an `acr` value, and `auth_time` says how fresh.
"""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final

from fastapi import Depends, HTTPException, status

from ..auth import require_ssf_user

PERMISSIONS_CLAIM: Final[str] = "ssf_permissions"
REQUEST: Final[str] = "ssf.recording.request"
REVIEW: Final[str] = "ssf.recording.review"
REVIEW_SWORN: Final[str] = "ssf.recording.review.sworn"
SUPERVISE: Final[str] = "ssf.recording.supervise"
CUSTODIAN: Final[str] = "ssf.recording.recovery.custodian"
# The tenant administrator's existing Studio permission (keycloak.ts reads it too).
TENANT_MANAGE: Final[str] = "ssf.configuration.tenant.manage"
RECORDING_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {REQUEST, REVIEW, REVIEW_SWORN, SUPERVISE, CUSTODIAN}
)

STEP_UP_ACR_ENV: Final[str] = "SSF_RECORDING_STEP_UP_ACR"
STEP_UP_MAX_AGE_ENV: Final[str] = "SSF_RECORDING_STEP_UP_MAX_AGE_SECONDS"
_DEFAULT_ACR: Final[str] = "mfa"
_DEFAULT_MAX_AGE: Final[int] = 300
_MAX_AGE_BOUNDS: Final[tuple[int, int]] = (30, 900)

Claims = dict[str, Any]


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


@dataclass(frozen=True)
class StepUpPolicy:
    acr_values: frozenset[str]
    max_age_seconds: int

    @classmethod
    def from_environment(cls) -> "StepUpPolicy":
        configured = os.environ.get(STEP_UP_ACR_ENV) or _DEFAULT_ACR
        values = frozenset(part.strip() for part in configured.split(",") if part.strip())
        return cls(values or frozenset({_DEFAULT_ACR}), _max_age())

    def satisfied_by(self, claims: Claims, now: float) -> bool:
        acr, auth_time = claims.get("acr"), claims.get("auth_time")
        if not isinstance(acr, str) or acr not in self.acr_values:
            return False
        if not isinstance(auth_time, int) or isinstance(auth_time, bool):
            return False
        return 0 <= now - auth_time <= self.max_age_seconds


def _max_age() -> int:
    try:
        value = int(os.environ.get(STEP_UP_MAX_AGE_ENV, _DEFAULT_MAX_AGE))
    except ValueError:
        return _DEFAULT_MAX_AGE
    low, high = _MAX_AGE_BOUNDS
    return value if low <= value <= high else _DEFAULT_MAX_AGE


async def require_step_up(claims: Annotated[Claims, Depends(require_ssf_user)]) -> Claims:
    """403 STEP_UP_REQUIRED tells the browser to re-authenticate with MFA and retry."""
    if not StepUpPolicy.from_environment().satisfied_by(claims, time.time()):
        raise coded(status.HTTP_403_FORBIDDEN, "STEP_UP_REQUIRED", "Fresh MFA login required")
    return claims
