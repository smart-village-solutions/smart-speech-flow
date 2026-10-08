"""Anonymous Studio content for the pages before login."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..content_responses import InstallationContentResponse, installation_response
from ..dependencies import get_studio_content
from ..studio_content_service import ContentUnavailable, StudioContentService
from ..studio_runtime_flow import correlation_id_from_request

router = APIRouter(prefix="/api/content", tags=["content"])

# Part of the route contract; the gateway's own reuse period is configured apart.
_CACHE_CONTROL = "public, max-age=60"


def _matches(if_none_match: str | None, etag: str) -> bool:
    if if_none_match is None:
        return False
    candidates = (candidate.strip() for candidate in if_none_match.split(","))
    return any(candidate in ("*", etag, f"W/{etag}") for candidate in candidates)


@router.get(
    "/installation",
    response_model=InstallationContentResponse,
    responses={
        304: {"description": "The browser's copy is current"},
        503: {"description": "No installation content was ever read; use bundled copy"},
    },
)
async def get_installation_content(
    request: Request,
    response: Response,
    content: Annotated[StudioContentService, Depends(get_studio_content)],
) -> InstallationContentResponse | Response:
    """Branding, legal links, start page and login texts, and the installation form."""
    try:
        installation = await content.installation_content(correlation_id_from_request(request))
    except ContentUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Installation content is temporarily unavailable",
            headers={"Cache-Control": "no-store"},
        ) from None
    headers = {
        "ETag": f'"{installation.configuration_revision}"',
        "Cache-Control": _CACHE_CONTROL,
    }
    if _matches(request.headers.get("If-None-Match"), headers["ETag"]):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    response.headers.update(headers)
    return installation_response(installation)
