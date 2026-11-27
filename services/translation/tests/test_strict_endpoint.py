import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from services.translation import app as translation_app
from services.translation.tests.test_strict_text import Model, Tokenizer


@pytest.fixture
def strict_service(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(translation_app, "m2m_model", Model())
    monkeypatch.setattr(translation_app, "m2m_tokenizer", Tokenizer())
    monkeypatch.setattr(translation_app, "supported_langs", ["de", "en"])

    async def idle(_request, _remaining, _request_id):
        return False

    monkeypatch.setattr(translation_app, "_strict_activity", idle, raising=False)
    with TestClient(translation_app.app) as client:
        yield client


def post(client, **updates):
    return client.post(
        "/translate/text",
        headers={"X-SSF-Lab-Token": "internal-secret"},
        json={
            "text": ["Hallo", "Welt"],
            "source_lang": "de",
            "target_lang": "en",
            "timeout_seconds": 1,
            "request_id": "a" * 32,
            **updates,
        },
    )


def test_internal_route_requires_enablement_and_shared_token(strict_service, monkeypatch):
    assert strict_service.post("/translate/text", json={}).status_code == 403
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "0")
    assert post(strict_service).status_code == 503
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.delenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN")
    assert post(strict_service).status_code == 503


def test_internal_route_returns_ordered_strict_results_and_no_store(strict_service):
    response = post(strict_service)
    assert response.status_code == 200
    assert response.json() == {"translations": ["Hallo", "Welt"]}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "updates",
    [
        {"text": [1]},
        {"text": [" "]},
        {"text": "Hello"},
        {"text": []},
        {"text": ["x"] * 11},
        {"text": ["x" * 5001]},
        {"debug": True},
        {"timeout_seconds": True},
        {"timeout_seconds": float("inf")},
        {"source_lang": "DE"},
        {"target_lang": "xx"},
    ],
)
def test_internal_route_rejects_invalid_input(strict_service, updates):
    # JSON cannot represent infinity; use an excessively large finite deadline.
    if updates.get("timeout_seconds") == float("inf"):
        updates = {"timeout_seconds": 999999}
    response = post(strict_service, **updates)
    assert response.status_code in (413, 422)
    detail = response.json()["detail"]
    if response.status_code == 413:
        assert detail["limits"] == {"max_items": 10, "max_characters": 5000}
    else:
        assert set(detail) == {"code", "message"}


@pytest.mark.parametrize("activity", [True, None])
def test_busy_or_unknown_activity_waits_only_until_request_deadline(
    strict_service, monkeypatch, activity
):
    async def unavailable(_request, _remaining, _request_id):
        return activity

    monkeypatch.setattr(translation_app, "_strict_activity", unavailable)
    response = post(strict_service, timeout_seconds=0.03)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == ("SYSTEM_BUSY" if activity else "UNAVAILABLE")
    assert response.headers["retry-after"] == "1"
    assert translation_app.m2m_model.calls == []


def test_activity_is_rechecked_between_each_segment(strict_service, monkeypatch):
    count = 0

    async def becomes_busy(_request, _remaining, _request_id):
        nonlocal count
        count += 1
        return count > 2

    monkeypatch.setattr(translation_app, "_strict_activity", becomes_busy)
    response = post(strict_service, timeout_seconds=0.03)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SYSTEM_BUSY"
    assert len(translation_app.m2m_model.calls) == 1


@pytest.mark.asyncio
async def test_deadline_keeps_background_slot_until_actual_inference_finishes(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "internal-secret")
    started, release = threading.Event(), threading.Event()

    class BlockedModel(Model):
        def generate(self, **kwargs):
            started.set()
            release.wait(2)
            return super().generate(**kwargs)

    monkeypatch.setattr(translation_app, "m2m_model", BlockedModel())
    monkeypatch.setattr(translation_app, "m2m_tokenizer", Tokenizer())
    monkeypatch.setattr(translation_app, "supported_langs", ["de", "en"])

    async def idle(_request, _remaining, _request_id):
        return False

    monkeypatch.setattr(translation_app, "_strict_activity", idle, raising=False)
    async with translation_app.lifespan(translation_app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=translation_app.app), base_url="http://test"
        ) as client:
            headers = {"X-SSF-Lab-Token": "internal-secret"}
            payload = {
                "text": ["Hello"],
                "source_lang": "de",
                "target_lang": "en",
                "timeout_seconds": 0.05,
                "request_id": "a" * 32,
            }
            try:
                first = await client.post("/translate/text", headers=headers, json=payload)
                assert started.is_set()
                assert first.status_code == 504
                second = await client.post("/translate/text", headers=headers, json=payload)
                assert second.status_code == 503
                assert second.json()["detail"]["code"] == "SYSTEM_BUSY"
                assert translation_app.app.state.translation_admission.in_flight == 1
            finally:
                release.set()
                await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1])
async def test_cancelled_legacy_worker_keeps_priority_until_it_finishes(monkeypatch, limit):
    from types import SimpleNamespace

    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(translation_app, "MAX_CONCURRENT_TRANSLATIONS", limit)
    model = Model()
    monkeypatch.setattr(translation_app, "m2m_model", model)
    monkeypatch.setattr(translation_app, "m2m_tokenizer", Tokenizer())
    monkeypatch.setattr(translation_app, "supported_langs", ["de", "en"])
    started, release = threading.Event(), threading.Event()

    def legacy(*_args):
        started.set()
        release.wait(2)
        return ["legacy"]

    monkeypatch.setattr(translation_app, "_translate_texts", legacy)

    async def idle(_request, _remaining, _request_id):
        return False

    monkeypatch.setattr(translation_app, "_strict_activity", idle)
    async with translation_app.lifespan(translation_app.app):
        normal = asyncio.create_task(
            translation_app._run_inference_off_loop(
                SimpleNamespace(app=translation_app.app),
                ["legacy"],
                "de",
                "en",
                {},
            )
        )
        while not started.is_set():
            await asyncio.sleep(0.001)
        normal.cancel()
        with pytest.raises(asyncio.CancelledError):
            await normal
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=translation_app.app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/translate/text",
                    headers={"X-SSF-Lab-Token": "internal-secret"},
                    json={
                        "text": ["Hello"],
                        "source_lang": "de",
                        "target_lang": "en",
                        "timeout_seconds": 0.03,
                        "request_id": "a" * 32,
                    },
                )
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "SYSTEM_BUSY"
            assert model.calls == []
        finally:
            release.set()
            await asyncio.sleep(0.02)


def test_unrepresentable_deadline_is_rejected_without_internal_error(strict_service):
    response = post(strict_service, timeout_seconds=10**1000)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("request_id", [None, "A" * 32, "g" * 32, "a" * 31, 123])
def test_private_request_id_must_be_canonical(strict_service, request_id):
    assert post(strict_service, request_id=request_id).status_code == 422


@pytest.mark.asyncio
async def test_cancelled_gateway_request_stops_after_active_segment(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ACTIVITY_URL", "https://gateway.test/activity")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(translation_app, "supported_langs", ["de", "en"])
    monkeypatch.setattr(translation_app, "m2m_tokenizer", Tokenizer())
    started, release = threading.Event(), threading.Event()

    class BlockedModel(Model):
        def generate(self, **kwargs):
            started.set()
            release.wait(2)
            return super().generate(**kwargs)

    model = BlockedModel()
    monkeypatch.setattr(translation_app, "m2m_model", model)
    cancelled = False

    def activity(request):
        if request.url.params.get("request_id") != "a" * 32:
            return httpx.Response(200, json={"busy": False, "cancelled": True})
        return httpx.Response(200, json={"busy": False, "cancelled": cancelled})

    async with translation_app.lifespan(translation_app.app):
        await translation_app.app.state.strict_http_client.aclose()
        async with httpx.AsyncClient(transport=httpx.MockTransport(activity)) as callback_client:
            translation_app.app.state.strict_http_client = callback_client
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=translation_app.app), base_url="http://test"
            ) as client:
                payload = {
                    "text": ["First", "Second"],
                    "source_lang": "de",
                    "target_lang": "en",
                    "timeout_seconds": 1,
                    "request_id": "a" * 32,
                }
                headers = {"X-SSF-Lab-Token": "internal-secret"}
                task = asyncio.create_task(
                    client.post("/translate/text", headers=headers, json=payload)
                )
                try:
                    for _ in range(100):
                        if started.is_set() or task.done():
                            break
                        await asyncio.sleep(0.001)
                    assert started.is_set()
                    cancelled = True
                    assert translation_app.app.state.translation_admission.in_flight == 1
                    assert (
                        await client.post("/translate/text", headers=headers, json=payload)
                    ).status_code == 503
                finally:
                    release.set()
                response = await task
                assert response.status_code == 499
                assert response.json()["detail"]["code"] == "REQUEST_CANCELLED"
                assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_activity_without_explicit_url_fails_closed(monkeypatch):
    monkeypatch.delenv("SSF_TEXT_TRANSLATION_ACTIVITY_URL", raising=False)
    assert await translation_app._strict_activity(None, 1.0, "request-id") is None
