"""POST /api/feedback.

Unauthenticated by design: the customer flow has no Keycloak identity, matching
routes/customer.py and the trust boundary in
docs/architecture/sva-studio-control-plane.md, which keeps customers with SSF
session tokens outside Studio IAM.

No handler here may put `submission.improvements` into a response or a log.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..feedback.models import (
    FeedbackAcceptedResponse,
    FeedbackSubmissionRequest,
    FeedbackTextTooLong,
)
from ..feedback.repository import FeedbackStorageUnavailable
from ..feedback.service import UnknownSession

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
