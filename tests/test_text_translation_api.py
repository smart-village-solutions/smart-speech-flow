"""Anonymous translation HTTP contract and bounded scheduling behavior."""

import asyncio
import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from tests.gateway_container import installed_gateway_dependencies


class Reply:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.headers = {"Retry-After": "1"} if status == 503 else {}

    def json(self):
        return self.payload


@pytest.fixture
def translation_client(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "internal-test-secret")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_LANGUAGES", "de,en,fr")
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: Reply({"languages": ["en", "de", "ar"], "count": 3})
    )

    def translate(url, **kwargs):
        assert url.endswith("/translate/text")
        assert kwargs["headers"]["X-SSF-Lab-Token"] == "internal-test-secret"
        assert 0 < kwargs["json"]["timeout_seconds"] < 30
        assert len(kwargs["json"]["request_id"]) == 32
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", translate)
    with installed_gateway_dependencies(app) as deps:
        yield TestClient(app), deps


PAYLOAD = {"text": ["Guten Tag.", "Ausweis bitte."], "source_lang": "de", "target_lang": "en"}


def test_ordered_anonymous_contract(translation_client):
    client, _ = translation_client
    response = client.post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {
        "translations": [{"text": "Good day."}, {"text": "Please bring ID."}],
        "source_lang": "de",
        "target_lang": "en",
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_language_list_is_actual_capability_intersection(translation_client):
    response = translation_client[0].get("/api/v1/languages")
    assert response.status_code == 200
    assert response.json() == {"languages": ["de", "en"]}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "updates,status",
    [
        ({"text": []}, 422),
        ({"text": [" "]}, 422),
        ({"text": [1]}, 422),
        ({"text": [None]}, 422),
        ({"text": "hello"}, 422),
        ({"text": ["x"] * 11}, 413),
        ({"text": ["😀" * 5001]}, 413),
        ({"source_lang": "DE"}, 422),
        ({"target_lang": "fr"}, 422),
        ({"target_lang": 1}, 422),
        ({"debug": True}, 422),
    ],
)
def test_strict_validation(translation_client, updates, status):
    response = translation_client[0].post("/api/v1/translate", json={**PAYLOAD, **updates})
    assert response.status_code == status
    assert "error" in response.json()
    assert response.headers["Cache-Control"] == "no-store"
    assert "Guten Tag" not in response.text


def test_malformed_json_is_safe_400(translation_client):
    response = translation_client[0].post("/api/v1/translate", content=b'{"text":')
    assert response.status_code == 400
    assert "error" in response.json()
    assert response.headers["Cache-Control"] == "no-store"


def test_chunked_body_cap(translation_client):
    def chunks():
        yield b"{" + b" " * 32000
        yield b" " * 34000

    response = translation_client[0].post("/api/v1/translate", content=chunks())
    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"


def test_identical_languages_preserve_original_without_inference(translation_client, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("inference invoked"))
    response = translation_client[0].post(
        "/api/v1/translate", json={**PAYLOAD, "target_lang": "de"}
    )
    assert response.status_code == 200
    assert response.json()["translations"] == [{"text": "Guten Tag."}, {"text": "Ausweis bitte."}]


@pytest.mark.parametrize(
    "payload",
    [{"translations": ["only one"]}, {"translations": [1, "x"]}, {"translations": ["", "x"]}, {}],
)
def test_unusable_output_is_atomic_502(translation_client, monkeypatch, payload):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Reply(payload))
    response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 502
    assert "translations" not in response.json()


@pytest.mark.parametrize(
    "status,code,want",
    [
        (413, "work_limit", 413),
        (503, "busy", 503),
        (504, "deadline", 504),
        (502, "incomplete_generation", 502),
        (401, "invalid_token", 503),
    ],
)
def test_upstream_failure_mapping(translation_client, monkeypatch, status, code, want):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: Reply(
            {"detail": {"code": code, "message": "PRIVATE TEXT", "limits": {"max_segments": 64}}},
            status,
        ),
    )
    response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == want
    assert "PRIVATE TEXT" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    if want == 503:
        assert response.headers["Retry-After"]


def test_rate_limit_ignores_forged_proxy_headers(translation_client):
    client, _ = translation_client
    for index in range(6):
        assert (
            client.post(
                "/api/v1/translate", json=PAYLOAD, headers={"X-Forwarded-For": f"192.0.2.{index}"}
            ).status_code
            == 200
        )
    response = client.post("/api/v1/translate", json=PAYLOAD, headers={"X-Real-IP": "192.0.2.90"})
    assert response.status_code == 429
    assert response.headers["Retry-After"]


@pytest.mark.parametrize("path", ["/api/v1/languages", "/api/v1/translate"])
def test_disabled_returns_404_with_no_store(monkeypatch, path):
    monkeypatch.delenv("SSF_TEXT_TRANSLATION_ENABLED", raising=False)
    with installed_gateway_dependencies(app):
        client = TestClient(app)
        response = (
            client.get(path) if path.endswith("languages") else client.post(path, json=PAYLOAD)
        )
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_enabled_without_secret_fails_closed(translation_client, monkeypatch):
    monkeypatch.delenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN")
    with installed_gateway_dependencies(app):
        response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_streaming_cap_stops_before_next_chunk(translation_client):
    from starlette.requests import Request

    from services.api_gateway.routes.text_translation import _read_payload
    from services.api_gateway.text_translation import TranslationError

    chunks = iter([b" " * 40000, b" " * 30000])

    async def receive():
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    request = Request({"type": "http", "headers": []}, receive)
    with pytest.raises(TranslationError) as caught:
        await _read_payload(request, translation_client[1].text_translation)
    assert caught.value.status == 413


@pytest.mark.parametrize("code", ["SYSTEM_BUSY", "UNAVAILABLE"])
def test_busy_and_unavailable_are_distinct_and_do_not_break_live_translation(
    translation_client, monkeypatch, code
):
    client, deps = translation_client
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: Reply({"detail": {"code": code, "message": "private"}}, 503),
    )
    for _ in range(4):
        response = client.post("/api/v1/translate", json=PAYLOAD)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == code
        assert response.headers["Retry-After"] == "1"
    assert deps.service_health.circuit_breakers["translation"].failure_count == 0


@pytest.mark.asyncio
async def test_cancelled_worker_retains_running_slot(translation_client, monkeypatch):
    from dataclasses import replace

    from services.api_gateway.text_translation import (
        TextTranslationService,
        TranslationError,
        TranslationRequest,
    )

    original = translation_client[1].text_translation
    service = TextTranslationService(original._breaker, replace(original.config, queue_size=0))
    started, finish = threading.Event(), threading.Event()

    def blocking_post(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", blocking_post)
    payload = TranslationRequest.model_validate(PAYLOAD)
    first = asyncio.create_task(service.translate(payload, time.monotonic() + 5))
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    try:
        with pytest.raises(TranslationError) as caught:
            await service.translate(payload, time.monotonic() + 5)
        assert caught.value.status == 503
        assert caught.value.code == "SYSTEM_BUSY"
        assert caught.value.retry_after == 1
    finally:
        finish.set()
        await asyncio.gather(*service._workers, return_exceptions=True)
    assert await service.translate(payload, time.monotonic() + 5) == [
        "Good day.",
        "Please bring ID.",
    ]


@pytest.mark.asyncio
async def test_queue_wait_expiry_reports_busy_and_never_starts_worker(
    translation_client, monkeypatch
):
    from services.api_gateway.text_translation import TranslationError, TranslationRequest

    service = translation_client[1].text_translation
    started, finish = threading.Event(), threading.Event()
    calls = []

    def blocking_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        started.set()
        assert finish.wait(2)
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", blocking_post)
    payload = TranslationRequest.model_validate(PAYLOAD)
    first = asyncio.create_task(service.translate(payload, time.monotonic() + 5))
    assert await asyncio.to_thread(started.wait, 1)
    try:
        with pytest.raises(TranslationError) as caught:
            await service.translate(payload, time.monotonic() + 0.02)
        assert caught.value.status == 503
        assert caught.value.code == "SYSTEM_BUSY"
        assert caught.value.retry_after == 1
        assert len(calls) == 1
    finally:
        finish.set()
        await first


@pytest.mark.asyncio
async def test_full_four_request_queue_returns_busy(translation_client, monkeypatch):
    from services.api_gateway.text_translation import TranslationError, TranslationRequest

    service = translation_client[1].text_translation
    started, finish = threading.Event(), threading.Event()

    def blocking_post(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", blocking_post)
    payload = TranslationRequest.model_validate(PAYLOAD)
    first = asyncio.create_task(service.translate(payload, time.monotonic() + 5))
    assert await asyncio.to_thread(started.wait, 1)
    waiting = [
        asyncio.create_task(service.translate(payload, time.monotonic() + 5)) for _ in range(4)
    ]
    await asyncio.sleep(0)
    try:
        with pytest.raises(TranslationError) as caught:
            await service.translate(payload, time.monotonic() + 5)
        assert caught.value.status == 503
        assert caught.value.code == "SYSTEM_BUSY"
    finally:
        for task in waiting:
            task.cancel()
        await asyncio.gather(*waiting, return_exceptions=True)
        finish.set()
        await first


@pytest.mark.asyncio
async def test_computation_deadline_retains_slot_until_worker_exits(
    translation_client, monkeypatch
):
    from dataclasses import replace

    from services.api_gateway.text_translation import (
        TextTranslationService,
        TranslationError,
        TranslationRequest,
    )

    original = translation_client[1].text_translation
    service = TextTranslationService(original._breaker, replace(original.config, queue_size=0))
    started, finish = threading.Event(), threading.Event()

    def blocking_post(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", blocking_post)
    payload = TranslationRequest.model_validate(PAYLOAD)
    try:
        with pytest.raises(TranslationError) as caught:
            await service.translate(payload, time.monotonic() + 0.3)
        assert caught.value.status == 504
        assert started.is_set()
        with pytest.raises(TranslationError) as full:
            await service.translate(payload, time.monotonic() + 5)
        assert full.value.code == "SYSTEM_BUSY"
    finally:
        finish.set()
        await asyncio.gather(*service._workers, return_exceptions=True)


def test_missing_container_is_safe_unavailable(translation_client, monkeypatch):
    monkeypatch.setattr(app.state, "dependencies", None)
    response = translation_client[0].get("/api/v1/languages")
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "capabilities",
    [None, {"languages": []}, {"languages": [1]}, {"languages": ["DE"]}, {"languages": ["zz"]}],
)
def test_unknown_capabilities_never_invent_languages(translation_client, monkeypatch, capabilities):
    monkeypatch.setattr(requests, "get", lambda *a, **k: Reply(capabilities))
    response = translation_client[0].get("/api/v1/languages")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UNAVAILABLE"


def test_discovery_uses_same_bounded_caller_quota(translation_client):
    client = translation_client[0]
    for _ in range(6):
        assert client.get("/api/v1/languages").status_code == 200
    response = client.get("/api/v1/languages", headers={"X-Forwarded-For": "10.20.30.40"})
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_finite_ip_tracker_fails_closed(translation_client):
    from dataclasses import replace

    from services.api_gateway.text_translation import TextTranslationService, TranslationError

    original = translation_client[1].text_translation
    service = TextTranslationService(original._breaker, replace(original.config, tracked_ips=1))
    service.admit_caller("192.0.2.1")
    with pytest.raises(TranslationError) as caught:
        service.admit_caller("192.0.2.2")
    assert caught.value.status == 503


def test_request_body_contract_is_published_in_openapi():
    operation = app.openapi()["paths"]["/api/v1/translate"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["text"]["type"] == "array"
    assert set(schema["required"]) == {"text", "source_lang", "target_lang"}


@pytest.mark.parametrize(
    "content,status",
    [
        (b"[" * 20000 + b"]" * 20000, 400),
        (b'{"text":["\\ud800"],"source_lang":"de","target_lang":"en"}', 422),
    ],
)
def test_deep_json_and_invalid_unicode_are_safe_client_errors(translation_client, content, status):
    response = translation_client[0].post("/api/v1/translate", content=content)
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_internal_request_id_reports_cancellation_until_worker_finishes(
    translation_client, monkeypatch
):
    from services.api_gateway.text_translation import TranslationRequest

    service = translation_client[1].text_translation
    started, finish = threading.Event(), threading.Event()
    request_ids = []

    def blocking_post(*args, **kwargs):
        request_ids.append(kwargs["json"]["request_id"])
        started.set()
        assert finish.wait(2)
        return Reply({"translations": ["Good day.", "Please bring ID."]})

    monkeypatch.setattr(requests, "post", blocking_post)
    task = asyncio.create_task(
        service.translate(TranslationRequest.model_validate(PAYLOAD), time.monotonic() + 5)
    )
    assert await asyncio.to_thread(started.wait, 1)
    request_id = request_ids[0]
    assert service.request_cancelled(request_id) is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        assert service.request_cancelled(request_id) is True
    finally:
        finish.set()
        await asyncio.gather(*service._workers, return_exceptions=True)
    assert service.request_cancelled(request_id) is None


@pytest.mark.asyncio
async def test_public_disconnect_cancels_queued_translation(translation_client, monkeypatch):
    from services.api_gateway.routes.text_translation import _until_disconnect

    cancelled = asyncio.Event()

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    async def waiting():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(asyncio.CancelledError):
        await _until_disconnect(DisconnectedRequest(), waiting())
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_local_deadline_during_conversation_reports_busy(translation_client, monkeypatch):
    from services.api_gateway.text_translation import (
        TextTranslationService,
        TranslationError,
        TranslationRequest,
    )

    original = translation_client[1].text_translation
    service = TextTranslationService(
        original._breaker, original.config, background_busy=lambda: True
    )
    finish = threading.Event()
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: (finish.wait(2), Reply({"languages": ["de", "en"]}))[1]
    )
    try:
        with pytest.raises(TranslationError) as caught:
            await service.translate(
                TranslationRequest.model_validate(PAYLOAD), time.monotonic() + 0.02
            )
        assert caught.value.status == 503
        assert caught.value.code == "SYSTEM_BUSY"
    finally:
        finish.set()
        await asyncio.gather(*service._workers, return_exceptions=True)


def test_metrics_count_success_and_busy_without_content_or_caller_labels(
    translation_client, monkeypatch
):
    from prometheus_client import CollectorRegistry

    from services.api_gateway.text_translation import TextTranslationMetrics

    client, deps = translation_client
    registry = CollectorRegistry()
    deps.text_translation.metrics = TextTranslationMetrics(registry)
    assert client.post("/api/v1/translate", json=PAYLOAD).status_code == 200
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: Reply({"detail": {"code": "SYSTEM_BUSY"}}, 503)
    )
    assert client.post("/api/v1/translate", json=PAYLOAD).status_code == 503
    assert (
        registry.get_sample_value(
            "text_translation_requests_total", {"operation": "translate", "outcome": "SUCCESS"}
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "text_translation_requests_total", {"operation": "translate", "outcome": "SYSTEM_BUSY"}
        )
        == 1
    )
    for family in registry.collect():
        for sample in family.samples:
            assert set(sample.labels) <= {"operation", "outcome", "le"}


def test_discovery_does_not_reserve_a_half_open_inference_probe(translation_client):
    from services.api_gateway.circuit_breaker import CircuitState

    breaker = translation_client[1].service_health.circuit_breakers["translation"]
    breaker.state = CircuitState.HALF_OPEN
    breaker.next_attempt_time = time.time() - 1
    assert translation_client[0].get("/api/v1/languages").status_code == 200
    with breaker.guard():
        breaker.record_success(0.01)


@pytest.mark.parametrize("configured", ["", "DE", "english"])
def test_invalid_optional_configuration_fails_closed_without_preventing_gateway_start(
    translation_client, monkeypatch, configured
):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_LANGUAGES", configured)
    with installed_gateway_dependencies(app):
        response = translation_client[0].get("/api/v1/languages")
        assert response.status_code == 503
        assert app.state.dependencies.speech_pipeline is not None


def test_legacy_upstream_capacity_code_is_busy(translation_client, monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: Reply({"detail": {"code": "SATURATED"}}, 503)
    )
    response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SYSTEM_BUSY"
    assert response.headers["Retry-After"] == "1"


def test_preflight_limits_forward_only_known_positive_integers(translation_client, monkeypatch):
    limits = {
        "max_segments": 64,
        "input_tokens": 256,
        "max_attempts": True,
        "total_output_tokens": -1,
        "output_tokens": "private",
        "unknown": "private",
    }
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: Reply({"detail": {"code": "WORK_LIMIT_EXCEEDED", "limits": limits}}, 413),
    )
    response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 413
    assert response.json()["error"]["limits"] == {"max_segments": 64, "input_tokens": 256}
    assert "private" not in response.text


@pytest.mark.parametrize(
    "limits", [None, {}, {"input_tokens": 0}, {"max_segments": 2**100}, {"max_segments": True}]
)
def test_upstream_preflight_without_usable_limits_is_unusable(
    translation_client, monkeypatch, limits
):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: Reply({"detail": {"code": "WORK_LIMIT_EXCEEDED", "limits": limits}}, 413),
    )
    response = translation_client[0].post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UNUSABLE_RESULT"


def test_explicit_compute_deadline_stays_504_when_conversation_arrives(
    translation_client, monkeypatch
):
    client, deps = translation_client
    deps.text_translation._background_busy = lambda: True
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: Reply({"detail": {"code": "DEADLINE_EXCEEDED"}}, 504),
    )
    response = client.post("/api/v1/translate", json=PAYLOAD)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "DEADLINE_EXCEEDED"
    assert deps.service_health.circuit_breakers["translation"].failure_count == 0
