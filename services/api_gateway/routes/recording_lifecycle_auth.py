"""Studio's organisation registry and access transfer API, using verified user bearers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from ..dependencies import optional_container
from ..recording.access_transfer import AccessTransfer
from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.lifecycle_models import ErrorResponse
from ..recording.organisation_keys import OrganisationKeys
from ..recording.permissions import (
    TENANT_MANAGE,
    TRANSFER,
    require_permission,
)
from ..recording.preparations import error
from ..recording.repository import RecordingStorageUnavailable
from ..tenant_context import StudioTenantContext, require_studio_tenant_context

T = TypeVar("T")


class LifecycleRoute(APIRoute):
    """Reject invalid submissions without reflecting field names, values or key material."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def validate(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as failure:
                code = "INVALID_KEY"
                for item in failure.errors():
                    location = item["loc"]
                    if item["type"] == "too_long" and location in (
                        ("body", "conversationIds"),
                        ("body", "wraps"),
                    ):
                        code = "TRANSFER_SCOPE_TOO_LARGE"
                        break
                    if location in (("body", "proof"), ("body", "savedConfirmation")):
                        code = "INVALID_PROOF"
                raise error(422, code) from None

        return validate


def lifecycle_router(prefix: str = "") -> APIRouter:
    return APIRouter(
        prefix=prefix,
        route_class=LifecycleRoute,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 410, 422, 503)},
    )


Tenant = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
Manager = Annotated[dict, Depends(require_permission(TENANT_MANAGE))]
Transfer = Annotated[dict, Depends(require_permission(TRANSFER))]
Reader = Annotated[dict, Depends(require_permission(TENANT_MANAGE, TRANSFER))]


def decoded(text: str, size: int, code: str) -> bytes:
    try:
        value = from_b64url(text)
        if len(value) != size or b64url(value) != text:
            raise ValueError
        return value
    except ValueError:
        raise error(422, code) from None


def services(request: Request, claims: dict[str, Any]) -> tuple[OrganisationKeys, AccessTransfer]:
    username = claims.get("preferred_username")
    if (
        not (claims.get("sid") or claims.get("session_state"))
        or isinstance(username, str)
        and username.startswith("service-account-")
        or claims.get("gty") in ("client-credentials", "client_credentials")
        or claims.get("clientId")
        or claims.get("client_id")
    ):
        raise error(403, "PERMISSION_REQUIRED")
    state = optional_container(request)
    org = getattr(state, "recording_organisation_keys", None)
    transfers = getattr(state, "recording_access_transfer", None)
    if org is None or transfers is None:
        raise error(503, "RECORDING_UNAVAILABLE")
    return org, transfers


async def stored(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except RecordingStorageUnavailable:
        raise error(503, "RECORDING_UNAVAILABLE") from None
