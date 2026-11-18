"""Background work must see queued and cancelled-but-running conversation work."""

import asyncio
import contextlib
import threading

import httpx
import pytest
from fastapi import FastAPI

from services.api_gateway.pipeline_admission import PipelineAdmission, PipelineAdmissionConfig
from services.api_gateway.routes.translation_activity import get_activity_admission, router


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1])
async def test_cancelled_running_pipeline_keeps_background_work_paused(limit):
    admission = PipelineAdmission(PipelineAdmissionConfig(max_concurrent=limit))
    started, finish = threading.Event(), threading.Event()

    def pipeline():
        started.set()
        finish.wait(3)

    assert admission.background_busy is False
    task = asyncio.create_task(admission.run(pipeline))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert admission.background_busy is True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert admission.background_busy is True
    finally:
        finish.set()
        for _ in range(100):
            if not admission.background_busy:
                break
            await asyncio.sleep(0.005)
    assert admission.background_busy is False


@pytest.mark.asyncio
async def test_queued_pipeline_counts_as_activity_and_cancellation_returns_it():
    admission = PipelineAdmission(PipelineAdmissionConfig(max_concurrent=1))
    # Occupy admission capacity without a worker; the real request waits for it.
    await admission._acquire()
    task = asyncio.create_task(admission.run(lambda: None))
    try:
        await asyncio.sleep(0)
        assert admission.background_busy is True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert admission.background_busy is False
    finally:
        admission._release()


@pytest.mark.asyncio
async def test_worker_exception_returns_activity():
    admission = PipelineAdmission()

    def fail():
        raise ValueError("example")

    with pytest.raises(ValueError):
        await admission.run(fail)
    assert admission.background_busy is False


@pytest.mark.asyncio
async def test_activity_route_authentication_and_unknown_state(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "lab-secret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_activity_admission] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/internal/text-translation/activity")
        assert denied.status_code == 404
        unknown = await client.get(
            "/internal/text-translation/activity", headers={"X-SSF-Lab-Token": "lab-secret"}
        )
        assert unknown.status_code == 503
        assert unknown.headers["cache-control"] == "no-store"
        admission = PipelineAdmission()
        app.dependency_overrides[get_activity_admission] = lambda: admission
        idle = await client.get(
            "/internal/text-translation/activity", headers={"X-SSF-Lab-Token": "lab-secret"}
        )
        assert idle.status_code == 200
        assert idle.json() == {"busy": False}


@pytest.mark.asyncio
async def test_internal_activity_checks_do_not_exhaust_global_client_quota(monkeypatch):
    from services.api_gateway.rate_limiter import RateLimitConfig, RateLimitMiddleware, RateLimits

    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "lab-secret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_activity_admission] = lambda: PipelineAdmission()
    app.add_middleware(RateLimitMiddleware, limits=RateLimits(RateLimitConfig(global_limit=1)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(3):
            response = await client.get(
                "/internal/text-translation/activity", headers={"X-SSF-Lab-Token": "lab-secret"}
            )
            assert response.status_code == 200


def test_unexpected_lab_failure_is_sanitized_and_not_cacheable():
    from fastapi.testclient import TestClient

    from services.api_gateway.unhandled_errors import UnhandledErrorMiddleware

    app = FastAPI()
    app.add_middleware(UnhandledErrorMiddleware)

    @app.post("/api/v1/translate")
    def fail():
        raise RuntimeError("sensitive input")

    response = TestClient(app, raise_server_exceptions=False).post("/api/v1/translate")
    assert response.status_code == 500
    assert "sensitive input" not in response.text
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_activity_callback_reports_cancelled_or_unknown_internal_request(monkeypatch):
    from types import SimpleNamespace

    from services.api_gateway.dependencies import get_text_translation_service

    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "lab-secret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_activity_admission] = lambda: PipelineAdmission()
    states = {"a" * 32: False, "b" * 32: True}
    app.dependency_overrides[get_text_translation_service] = lambda: SimpleNamespace(
        request_cancelled=lambda request_id: states.get(request_id)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for request_id, wanted in (("a" * 32, False), ("b" * 32, True), ("c" * 32, True)):
            response = await client.get(
                "/internal/text-translation/activity",
                params={"request_id": request_id},
                headers={"X-SSF-Lab-Token": "lab-secret"},
            )
            assert response.status_code == 200
            assert response.json() == {"busy": False, "cancelled": wanted}
