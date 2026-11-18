"""Internal, fail-closed activity signal for background laboratory translation."""

from __future__ import annotations

import hmac
import os
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..dependencies import get_text_translation_service, optional_container
from ..pipeline_admission import PipelineAdmission
from ..text_translation import TextTranslationService

router = APIRouter()


def get_activity_admission(request: Request) -> PipelineAdmission | None:
    container = optional_container(request)
    return container.pipeline_admission if container is not None else None


@router.get("/internal/text-translation/activity", include_in_schema=False)
async def translation_activity(
    request: Request,
    admission: PipelineAdmission | None = Depends(get_activity_admission),
    service: TextTranslationService | None = Depends(get_text_translation_service),
) -> JSONResponse:
    """Only an authenticated internal caller may observe pipeline activity."""
    token = os.environ.get("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "")
    supplied = request.headers.get("X-SSF-Lab-Token", "")
    headers = {"Cache-Control": "no-store"}
    if (
        os.environ.get("SSF_TEXT_TRANSLATION_ENABLED") != "1"
        or not token
        or not hmac.compare_digest(supplied.encode(), token.encode())
    ):
        return JSONResponse({"detail": "Not found"}, status_code=404, headers=headers)
    if admission is None:
        return JSONResponse({"detail": "Activity unavailable"}, status_code=503, headers=headers)
    payload = {"busy": admission.background_busy}
    request_id = request.query_params.get("request_id")
    if request_id is not None:
        if re.fullmatch(r"[a-f0-9]{32}", request_id) is None:
            return JSONResponse(
                {"detail": "Invalid request reference"}, status_code=400, headers=headers
            )
        # Ephemeral references are private cancellation handles, not public jobs.
        # A missing handle after timeout, restart or completion is never runnable.
        payload["cancelled"] = service is None or service.request_cancelled(request_id) is not False
    return JSONResponse(payload, headers=headers)
