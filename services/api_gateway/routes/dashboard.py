"""Authenticated task overview and content-free completed review summaries."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from ..auth import require_ssf_user
from ..dashboard import Dashboard, DashboardCursor, DashboardUnavailableError
from ..dashboard_repository import DashboardRecords
from ..dependencies import optional_container
from ..recording.permissions import REVIEW, coded, permissions_of, require_permission
from ..tenant_context import StudioTenantContext, require_admin_ref, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(tags=["dashboard"], route_class=ValueFreeValidationRoute)
Tenant = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
User = Annotated[dict[str, Any], Depends(require_ssf_user)]
Reviewer = Annotated[dict[str, Any], Depends(require_permission(REVIEW))]


def get_dashboard(request: Request) -> Dashboard:
    dependencies = optional_container(request)
    if dependencies is None:
        raise coded(503, "DASHBOARD_UNAVAILABLE", "Dashboard is not available")
    repository = dependencies.recording_repository
    try:
        cursor = DashboardCursor.from_environment()
    except ValueError:
        raise coded(503, "DASHBOARD_UNAVAILABLE", "A shared dashboard secret is required") from None
    return Dashboard(
        dependencies.session_manager.store,
        DashboardRecords(repository.pool) if repository is not None else None,
        dependencies.pseudonymizer,
        cursor,
    )


def get_dashboard_records(request: Request) -> DashboardRecords:
    dependencies = optional_container(request)
    repository = getattr(dependencies, "recording_repository", None)
    if repository is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return DashboardRecords(repository.pool)


@router.get("/api/admin/dashboard/conversations")
async def conversations(
    context: Tenant,
    claims: User,
    owner: Annotated[str, Depends(require_admin_ref)],
    dashboard: Annotated[Dashboard, Depends(get_dashboard)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
) -> dict[str, Any]:
    try:
        return await dashboard.conversations(
            context.tenant_id,
            claims["sub"],
            owner,
            permissions_of(claims),
            limit,
            cursor,
        )
    except ValueError:
        raise coded(400, "CURSOR_INVALID", "Dashboard cursor is invalid") from None
    except DashboardUnavailableError:
        raise coded(503, "DASHBOARD_UNAVAILABLE", "Dashboard is not available") from None


@router.get("/api/admin/recording/verifications/{verification_id}/result")
async def completed_review_result(
    verification_id: uuid.UUID,
    context: Tenant,
    claims: Reviewer,
    records: Annotated[DashboardRecords, Depends(get_dashboard_records)],
) -> dict[str, Any]:
    try:
        result = await records.completed_result(
            context.tenant_id, claims["sub"], str(verification_id)
        )
    except DashboardUnavailableError:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available") from None
    if result is None:
        raise coded(404, "VERIFICATION_NOT_FOUND", "Verification is not available")
    return result
