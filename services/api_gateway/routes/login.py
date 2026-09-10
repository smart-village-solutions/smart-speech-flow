"""Anonymous browser-safe routes for selecting a Studio tenant."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..studio_login_directory import (
    StudioLoginDirectoryConfigurationError,
    StudioLoginDirectoryService,
    get_studio_login_directory_service,
)
from ..studio_login_directory_client import StudioLoginDirectoryClientError
from ..studio_runtime_token import StudioTokenError

UNAVAILABLE_DETAIL = "The login directory is temporarily unavailable"

router = APIRouter(prefix="/api/login", tags=["login"])


class LoginTenantResponse(BaseModel):
    """The browser-safe fields needed to start one tenant's login flow."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName")
    realm: str


class LoginTenantDirectoryResponse(BaseModel):
    """The public tenant chooser response."""

    tenants: list[LoginTenantResponse]


@router.get("/tenants", response_model=LoginTenantDirectoryResponse)
async def list_login_tenants(
    request: Request,
    directory: Annotated[
        StudioLoginDirectoryService,
        Depends(get_studio_login_directory_service),
    ],
) -> LoginTenantDirectoryResponse:
    """Return only validated fields that are safe for an anonymous browser."""
    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid4())
    try:
        result = await directory.get(correlation_id)
    except (
        StudioLoginDirectoryClientError,
        StudioTokenError,
        StudioLoginDirectoryConfigurationError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from None
    return LoginTenantDirectoryResponse(
        tenants=[
            LoginTenantResponse(
                id=tenant.id,
                displayName=tenant.display_name,
                realm=tenant.realm,
            )
            for tenant in result.tenants
        ]
    )
