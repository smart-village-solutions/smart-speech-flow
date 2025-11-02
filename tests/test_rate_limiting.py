"""Tests for the API gateway rate limiting middleware."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.rate_limiter import RateLimitConfig
from services.api_gateway.session_manager import (
    ClientType,
    Session,
    SessionMessage,
    SessionStatus,
    session_manager,
)
from services.api_gateway.routes import session as session_routes

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_session_manager() -> None:
    session_manager.reset(clear_persistence=True)
    yield
    session_manager.reset(clear_persistence=True)

def _register_active_session() -> str:
    session_id = "RATE1234"
    session = Session(
        id=session_id,
        customer_language="en",
        admin_language="de",
        status=SessionStatus.ACTIVE,
    )
    session_manager.sessions[session_id] = session
    session_manager.active_admin_session = session_id
    return session_id


def _patch_pipeline(monkeypatch):
    def fake_process_text_pipeline(text: str, source_lang: str, target_lang: str):
        return {
            "error": False,
            "asr_text": text,
            "translation_text": f"translated:{text}",
            "audio_bytes": None,
            "debug": {"total_duration": 0.05},
        }

    async def fake_create_session_message(
        session_id: str,
        client_type: ClientType,
        original_text: str,
        translated_text: str,
        audio_bytes,
        source_lang: str,
        target_lang: str,
    ) -> SessionMessage:
        message = SessionMessage(
            id=str(uuid.uuid4()),
            sender=client_type,
            original_text=original_text,
            translated_text=translated_text,
            audio_base64=None,
            source_lang=source_lang,
            target_lang=target_lang,
            timestamp=datetime.now(),
        )
        session_manager.add_message(session_id, message)
        return message

    monkeypatch.setattr(session_routes, "process_text_pipeline", fake_process_text_pipeline)
    monkeypatch.setattr(session_routes, "create_session_message", fake_create_session_message)


def test_session_message_rate_limit(monkeypatch):
    session_id = _register_active_session()
    _patch_pipeline(monkeypatch)

    config_limit = RateLimitConfig().message_limit
    if config_limit <= 0:
        pytest.skip("Message rate limiting not enabled")

    payload = {
        "text": "hello",
        "source_lang": "en",
        "target_lang": "de",
        "client_type": "admin",
    }

    url = f"/api/session/{session_id}/message"

    for _ in range(config_limit):
        response = client.post(url, json=payload)
        assert response.status_code == 200

    blocked_response = client.post(url, json=payload)
    assert blocked_response.status_code == 429
    body = blocked_response.json()
    assert body["error_code"] == "SESSION_MESSAGE_RATE_LIMIT"
    assert body["status"] == "error"
    assert body["details"]["limit"] == config_limit
    assert "Retry-After" in blocked_response.headers