"""Exercise both real API adapters and cancellation callback without a GPU/network."""

import threading

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.circuit_breaker import CircuitBreaker
from services.api_gateway.dependencies import get_text_translation_service
from services.api_gateway.pipeline_admission import PipelineAdmission
from services.api_gateway.routes.text_translation import router as public_router
from services.api_gateway.routes.translation_activity import get_activity_admission
from services.api_gateway.routes.translation_activity import router as activity_router
from services.api_gateway.text_translation import TextTranslationConfig, TextTranslationService
from services.translation import app as translation
from services.translation.tests.test_strict_text import Model, Tokenizer


@pytest.fixture
def laboratory(monkeypatch):
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_ENABLED", "1")
    monkeypatch.setenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "integration-secret")
    monkeypatch.setattr(translation, "m2m_model", Model())
    monkeypatch.setattr(translation, "m2m_tokenizer", Tokenizer())
    monkeypatch.setattr(translation, "tokenizer_lock", threading.Lock())
    monkeypatch.setattr(translation, "supported_langs", ["de", "en"])
    monkeypatch.setattr(translation, "model_loaded", True)
    gateway = FastAPI()
    gateway.include_router(public_router)
    gateway.include_router(activity_router)
    admission = PipelineAdmission()
    service = TextTranslationService(
        CircuitBreaker("translation"),
        TextTranslationConfig(enabled=True, internal_token="integration-secret"),
        background_busy=lambda: admission.background_busy,
    )
    gateway.dependency_overrides[get_text_translation_service] = lambda: service
    gateway.dependency_overrides[get_activity_admission] = lambda: admission

    with TestClient(translation.app) as upstream:
        # Only replace the network boundary. Callback still traverses its real
        # authenticated gateway route and reads the real cancellation registry.
        original_get = translation.httpx.AsyncClient.get

        async def callback(client, url, **kwargs):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://gateway"
            ) as local:
                return await original_get(local, "/internal/text-translation/activity", **kwargs)

        monkeypatch.setattr(translation.httpx.AsyncClient, "get", callback)
        monkeypatch.setattr(requests, "get", lambda url, **kw: upstream.get("/languages"))
        monkeypatch.setattr(
            requests,
            "post",
            lambda url, **kw: upstream.post(
                "/translate/text", json=kw["json"], headers=kw["headers"]
            ),
        )
        with TestClient(gateway) as public:
            yield public, service, admission


def test_anonymous_gateway_to_strict_service_preserves_text_and_private_protocol(laboratory):
    public, service, _ = laboratory
    response = public.post(
        "/api/v1/translate",
        json={
            "text": ["Guten Tag.\n\nAusweis bitte.", "Zweiter Text."],
            "source_lang": "de",
            "target_lang": "en",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "translations": [{"text": "Guten Tag.\n\nAusweis bitte."}, {"text": "Zweiter Text."}],
        "source_lang": "de",
        "target_lang": "en",
    }
    assert response.headers["cache-control"] == "no-store"
    assert "request_id" not in response.text
    assert service._active_requests == {}


def test_busy_conversation_returns_public_system_busy_across_both_services(laboratory):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    public, service, admission = laboratory
    service.config = replace(service.config, deadline_seconds=0.5)
    started, finish = threading.Event(), threading.Event()

    def conversation():
        started.set()
        finish.wait(3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(lambda: asyncio.run(admission.run(conversation)))
        try:
            assert started.wait(2)
            response = public.post(
                "/api/v1/translate",
                json={"text": ["Hallo."], "source_lang": "de", "target_lang": "en"},
            )
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "SYSTEM_BUSY"
            assert int(response.headers["retry-after"]) >= 1
            assert translation.m2m_model.calls == []
        finally:
            finish.set()
            running.result(timeout=2)
