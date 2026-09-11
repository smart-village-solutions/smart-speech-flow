"""POST /api/feedback, and the authorised Studio read path over it.

The submit route is unauthenticated by design: the customer flow has no
Keycloak identity, matching routes/customer.py and the trust boundary in
docs/architecture/sva-studio-control-plane.md, which keeps customers with SSF
session tokens outside Studio IAM.

The read routes are the opposite. They serve Studio staff, so they take the
tenant from the signed `studio_tenant_id` claim through
require_studio_tenant_context, which also rejects any tenant selector supplied
by the request. No handler may read across tenants on a caller's say-so.

No handler here may put `submission.improvements` into a response or a log.
The single exception is the detail route, which exists to disclose it to an
authorised operator and writes an access audit row for every disclosure.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from ..feedback.models import (
    FeedbackAcceptedResponse,
    FeedbackSubmissionRequest,
    FeedbackTextTooLong,
)
from ..auth import require_ssf_user
from ..feedback.read import (
    FeedbackDetail,
    FeedbackNotFound,
    FeedbackSummary,
    FeedbackTextUnreadable,
)
from ..feedback.repository import FeedbackStorageUnavailable
from ..feedback.service import UnknownSession
from ..tenant_context import StudioTenantContext, require_studio_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])


_RETRY_AFTER_SECONDS = "30"


def get_feedback_service(request: Request):
    """FastAPI provider, following the app.state pattern used across app.py.

    None when the feedback store is unconfigured or could not be reached at
    startup. The gateway serves the whole conversation pipeline, so that
    degrades submissions to a retryable 503 rather than refusing to boot.
    """
    service = getattr(request.app.state, "feedback_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback is temporarily unavailable; please retry",
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        )
    return service


@router.post(
    "/feedback",
    response_model=FeedbackAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit voluntary feedback for a session",
)
async def submit_feedback(
    submission: FeedbackSubmissionRequest,
    service=Depends(get_feedback_service),
) -> FeedbackAcceptedResponse:
    try:
        feedback_id = await service.submit(submission)
    except UnknownSession:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The session is not known",
        ) from None
    except FeedbackTextTooLong as error:
        # The exception carries the limit, never the text. `from None` keeps
        # the submitted value out of the traceback a handler might serialise.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from None
    except FeedbackStorageUnavailable:
        # No exception text: an asyncpg error carries the bound parameters,
        # and the free text is one of them.
        logger.warning("Feedback storage unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback could not be stored; please retry",
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        ) from None

    return FeedbackAcceptedResponse(feedback_id=feedback_id)


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class FeedbackSummaryResponse(BaseModel):
    """A listed record. Carries no free text, only whether any exists."""

    feedback_id: UUID
    session_ref: str
    translation_quality: int
    performance: int
    usability: int
    net_promoter_score: int
    has_improvements: bool
    form_version: str
    analytics_state: str
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, summary: FeedbackSummary) -> "FeedbackSummaryResponse":
        return cls(**asdict(summary))


class FeedbackListResponse(BaseModel):
    """One page of a tenant's feedback."""

    items: list[FeedbackSummaryResponse]


def get_feedback_read_service(request: Request):
    """FastAPI provider for the authorised read path.

    None when the read role is unconfigured, which is a supported deployment:
    a site that never granted Studio read access should answer 503 here while
    POST /api/feedback keeps working.
    """
    service = getattr(request.app.state, "feedback_read_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback reading is temporarily unavailable; please retry",
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        )
    return service


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="List this tenant's feedback submissions",
)
async def list_feedback(
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    claims: Annotated[dict, Depends(require_ssf_user)],
    service=Depends(get_feedback_read_service),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> FeedbackListResponse:
    try:
        summaries = await service.list_for_tenant(
            tenant_id=context.tenant_id,
            accessed_by=_operator(claims),
            limit=limit,
            offset=offset,
        )
    except FeedbackStorageUnavailable:
        raise _read_unavailable() from None
    return FeedbackListResponse(
        items=[FeedbackSummaryResponse.of(summary) for summary in summaries]
    )


def _operator(claims: dict) -> str:
    """Who the audit row names. `sub` is the only claim guaranteed present."""
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else "unknown"


class FeedbackDetailResponse(FeedbackSummaryResponse):
    """A listed record plus the text it was hiding. Audited on every read."""

    improvements: str | None

    @classmethod
    def of_detail(cls, detail: FeedbackDetail) -> "FeedbackDetailResponse":
        return cls(**asdict(detail.summary), improvements=detail.improvements)


@router.get(
    "/feedback/{feedback_id}",
    response_model=FeedbackDetailResponse,
    summary="Read one feedback submission, including its free text",
)
async def read_feedback(
    feedback_id: UUID,
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    claims: Annotated[dict, Depends(require_ssf_user)],
    service=Depends(get_feedback_read_service),
) -> FeedbackDetailResponse:
    try:
        detail = await service.read_for_tenant(
            feedback_id=feedback_id,
            tenant_id=context.tenant_id,
            accessed_by=_operator(claims),
        )
    except FeedbackNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such feedback record",
        ) from None
    except FeedbackTextUnreadable:
        # Not retryable and not the caller's fault: the record exists but the
        # deployment's key cannot open it. Said explicitly, because a bare 500
        # sends an operator looking for a crash rather than at the key.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored text could not be decrypted with the configured key",
        ) from None
    except FeedbackStorageUnavailable:
        raise _read_unavailable() from None
    return FeedbackDetailResponse.of_detail(detail)


def _read_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Feedback could not be read; please retry",
        headers={"Retry-After": _RETRY_AFTER_SECONDS},
    )
