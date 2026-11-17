"""Shared-key laboratory routes with streamed request-body limits."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, TypeVar

from fastapi import APIRouter, Depends, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError

from ..dependencies import get_text_translation_service
from ..text_translation import (
    LanguagesResponse,
    TextTranslationService,
    TranslationError,
    TranslationRequest,
    TranslationResponse,
    deadline_error,
    unavailable,
)

T = TypeVar("T")

router = APIRouter(prefix="/api/v1", tags=["text-translation"])
client_api_key = APIKeyHeader(
    name="X-API-Key", scheme_name="TextTranslationApiKey", auto_error=False
)
_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"description": description}
    for status, description in (
        (400, "Malformed JSON"),
        (401, "Missing or invalid X-API-Key (INVALID_API_KEY)"),
        (404, "Feature disabled"),
        (413, "Request exceeds limits"),
        (422, "Invalid fields or unsupported languages"),
        (429, "Caller rate limit"),
        (502, "Unusable upstream result"),
        (503, "Translation unavailable or busy"),
        (504, "Total deadline exceeded"),
    )
}


def _error(exc: TranslationError) -> JSONResponse:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.limits is not None:
        error["limits"] = exc.limits
    headers = {"Cache-Control": "no-store"}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse({"error": error}, status_code=exc.status, headers=headers)


def _ready(
    service: TextTranslationService | None, request: Request, api_key: str | None
) -> TextTranslationService:
    if service is None:
        if os.getenv("SSF_TEXT_TRANSLATION_ENABLED", "0") != "1":
            raise TranslationError(404, "NOT_FOUND", "Not found.")
        raise unavailable()
    service.check_available()
    service.authenticate(api_key)
    service.admit_caller(request.client.host if request.client else "unknown")
    return service


async def _read_payload(request: Request, service: TextTranslationService) -> TranslationRequest:
    limit = service.config.body_bytes
    too_large = TranslationError(
        413,
        "BODY_LIMIT_EXCEEDED",
        "Request body exceeds the byte limit.",
        limits={"max_body_bytes": limit},
    )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise too_large
        except ValueError:
            raise TranslationError(400, "INVALID_JSON", "Invalid request body.") from None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise too_large
        body.extend(chunk)
    try:
        # Reject NaN/Infinity, which are not JSON values.
        def reject_constant(value: str) -> None:
            raise ValueError("invalid JSON constant")

        data = json.loads(body, parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise TranslationError(400, "INVALID_JSON", "Malformed JSON request.") from None
    try:
        payload = TranslationRequest.model_validate(data)
    except ValidationError:
        # Pydantic's raw error includes supplied text, so never return it.
        raise TranslationError(
            422, "INVALID_REQUEST", "Invalid translation request fields."
        ) from None
    service.validate(payload)
    return payload


async def _until_disconnect(request: Request, operation: Awaitable[T]) -> T:
    """Cancel the waiter promptly after a public caller disconnects."""
    task = asyncio.ensure_future(operation)

    async def disconnected() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return await task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise asyncio.CancelledError
    finally:
        watcher.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(watcher, task, return_exceptions=True)


@router.post(
    "/translate",
    response_model=TranslationResponse,
    responses=_ERRORS,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": TranslationRequest.model_json_schema()}},
        }
    },
)
async def translate(
    request: Request,
    service: TextTranslationService | None = Depends(get_text_translation_service),
    api_key: str | None = Security(client_api_key),
) -> JSONResponse:
    started = time.monotonic()
    try:
        active = _ready(service, request, api_key)
        deadline = started + active.config.deadline_seconds
        # Includes the streamed body read, validation, queue and downstream work.
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            payload = await _read_payload(request, active)
        translations = await _until_disconnect(request, active.translate(payload, deadline))
        active.metrics.observe("translate", "SUCCESS", started)
        return JSONResponse(
            {
                "translations": [{"text": value} for value in translations],
                "source_lang": payload.source_lang,
                "target_lang": payload.target_lang,
            },
            headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        error = deadline_error()
        if service is not None:
            service.metrics.observe("translate", error.code, started)
        return _error(error)
    except TranslationError as exc:
        if service is not None:
            service.metrics.observe("translate", exc.code, started)
        return _error(exc)


@router.get("/languages", response_model=LanguagesResponse, responses=_ERRORS)
async def languages(
    request: Request,
    service: TextTranslationService | None = Depends(get_text_translation_service),
    api_key: str | None = Security(client_api_key),
) -> JSONResponse:
    started = time.monotonic()
    try:
        active = _ready(service, request, api_key)
        result = await _until_disconnect(
            request, active.languages(started + active.config.deadline_seconds)
        )
        active.metrics.observe("languages", "SUCCESS", started)
        return JSONResponse({"languages": result}, headers={"Cache-Control": "no-store"})
    except TranslationError as exc:
        if service is not None:
            service.metrics.observe("languages", exc.code, started)
        return _error(exc)
