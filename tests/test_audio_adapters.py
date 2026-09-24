"""The audio validator and the audio store are the ones each app was built with (#228)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.api_gateway import app as app_module
from services.api_gateway.app import app, audio_cleanup_task
from services.api_gateway.audio_processing import AudioValidationResult
from services.api_gateway.audio_storage import AUDIO_BASE_DIR, AudioStore, AudioVariant
from services.api_gateway.service_health import ServiceHealthManager
from services.api_gateway.tenant_session import TenantSessionKey
from tests.gateway_contract.contract_support import wav_bytes

STUDIO_ENVIRONMENT = (
    "STUDIO_RUNTIME_CONFIGURATION_BASE_URL",
    "STUDIO_RUNTIME_FIXED_TOKEN",
    "STUDIO_RUNTIME_TOKEN_URL",
    "STUDIO_RUNTIME_CLIENT_ID",
    "STUDIO_RUNTIME_CLIENT_SECRET",
    "STUDIO_RUNTIME_AUDIENCE",
)
TTS_AUDIO = wav_bytes(0.2)


class _Reply:
    def __init__(self, payload: dict[str, Any] | None = None, content: bytes = b"") -> None:
        self.status_code = 200
        self._payload = payload or {}
        self.content = content
        self.headers = {"content-type": "audio/wav" if content else "application/json"}
        self.text = str(self._payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class SpeechServices:
    """ASR, translation and TTS at their HTTP boundary, recording what ASR hears."""

    def __init__(self) -> None:
        self.transcribed: list[bytes] = []

    def post(self, url: str, **options: Any) -> _Reply:
        if url.endswith("/transcribe"):
            self.transcribed.append(options["files"]["file"][1])
            return _Reply({"text": "Guten Tag"})
        if url.endswith("/translate"):
            return _Reply({"translations": "Good day"})
        return _Reply(content=TTS_AUDIO)


class StubValidator:
    """Accepts everything and hands on its own bytes, or rejects everything."""

    def __init__(self, *, accept: bool) -> None:
        self.accept = accept
        self.calls: list[tuple[bytes, bool]] = []

    def validate(self, audio_bytes: bytes, *, normalize: bool) -> AudioValidationResult:
        self.calls.append((audio_bytes, normalize))
        if self.accept:
            return AudioValidationResult(is_valid=True, processed_audio=b"VALIDATED")
        return AudioValidationResult(
            is_valid=False,
            error_code="STUB_REJECTED",
            error_message="rejected by the stub validator",
            details={},
            validation_time_ms=0,
        )


@pytest.fixture
def speech(monkeypatch: pytest.MonkeyPatch) -> SpeechServices:
    import requests

    services = SpeechServices()
    monkeypatch.setattr(requests, "post", services.post)
    return services


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _active_session(client: TestClient) -> str:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    activated = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert activated.status_code == 200, activated.text
    return session_id


def _send_audio(client: TestClient, path: str, body: bytes):
    return client.post(
        path,
        files={"file": ("speech.wav", body, "audio/wav")},
        data={"source_lang": "de", "target_lang": "en"},
    )


def test_the_message_path_runs_the_apps_validator_once(client, speech, gateway_dependencies):
    validator = StubValidator(accept=True)
    gateway_dependencies.speech_pipeline.validator = validator
    session_id = _active_session(client)
    recording = wav_bytes()

    response = _send_audio(client, f"/api/admin/session/{session_id}/message", recording)

    assert response.status_code == 200, response.text
    assert validator.calls == [(recording, True)]
    assert speech.transcribed == [b"VALIDATED"]


def test_the_message_path_reports_the_apps_validator_refusal(client, speech, gateway_dependencies):
    gateway_dependencies.speech_pipeline.validator = StubValidator(accept=False)
    session_id = _active_session(client)

    response = _send_audio(client, f"/api/admin/session/{session_id}/message", wav_bytes())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert (detail["error_code"], detail["error_message"]) == (
        "STUB_REJECTED",
        "rejected by the stub validator",
    )
    assert speech.transcribed == []


@pytest.mark.parametrize("path", ["/pipeline", "/upload"])
def test_the_pipeline_routes_run_the_apps_validator(client, speech, gateway_dependencies, path):
    validator = StubValidator(accept=True)
    gateway_dependencies.speech_pipeline.validator = validator
    recording = wav_bytes()

    response = _send_audio(client, path, recording)

    assert response.status_code == 200, response.text
    assert validator.calls == [(recording, True)]
    assert speech.transcribed == [b"VALIDATED"]


def test_a_running_app_keeps_audio_in_the_directory_it_started_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, speech
):
    """Read when the lifespan builds the container, not when the module was imported.

    Without Studio no write is authorised, so termination settles the message
    as refused and removes its audio through the same store.
    """
    for variable in STUDIO_ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))
    assert AUDIO_BASE_DIR != tmp_path
    # Health polls that reach nothing would open the breakers mid-test.
    monkeypatch.setattr(
        ServiceHealthManager,
        "_perform_health_request",
        AsyncMock(return_value={"status_code": 200, "response_time": 0.0}),
    )
    cleanup_tasks: list[tuple[Any, AudioStore]] = []

    async def record_cleanup_task(sessions: Any, audio_store: AudioStore) -> None:
        cleanup_tasks.append((sessions, audio_store))

    monkeypatch.setattr(app_module, "audio_cleanup_task", record_cleanup_task)
    recording = wav_bytes()

    with TestClient(app) as client:
        dependencies = app.state.dependencies
        assert dependencies.audio_store.base_dir == tmp_path
        assert cleanup_tasks == [(dependencies.session_manager, dependencies.audio_store)]
        session_id = _active_session(client)

        sent = _send_audio(client, f"/api/admin/session/{session_id}/message", recording)
        assert sent.status_code == 200, sent.text
        message_id = sent.json()["message_id"]
        key = TenantSessionKey("tenant-test", session_id)
        stored = {
            variant: tmp_path / "v2" / key.tenant_ref / session_id / variant.value
            for variant in AudioVariant
        }
        assert (stored[AudioVariant.ORIGINAL] / f"{message_id}.wav").read_bytes() == recording
        assert (stored[AudioVariant.TRANSLATED] / f"{message_id}.wav").read_bytes() == TTS_AUDIO
        assert not (AUDIO_BASE_DIR / "v2" / key.tenant_ref / session_id).exists()
        served = client.get(f"/api/admin/session/{session_id}/audio/{message_id}/translated.wav")
        assert served.content == TTS_AUDIO

        terminated = client.delete(f"/api/admin/session/{session_id}/terminate")
        assert terminated.status_code == 200, terminated.text

    for directory in stored.values():
        assert not (directory / f"{message_id}.wav").exists()


def test_the_cleanup_task_removes_expired_audio_from_its_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    store = AudioStore(tmp_path)
    key = TenantSessionKey("tenant-test", "CLEANUP1")
    expired = store.save(key, "m1", AudioVariant.ORIGINAL, b"wav")
    fresh = store.save(key, "m2", AudioVariant.ORIGINAL, b"wav")
    old = time.time() - 25 * 3600
    os.utime(expired, (old, old))
    monkeypatch.delenv("SSF_CONTENT_RETENTION_HOURS", raising=False)
    sleeps: list[float] = []

    async def one_pass(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise RuntimeError("stop after one pass")

    class Sessions:
        def sweep_expired_content(self, _now: Any) -> dict[str, int]:
            return {"refused_removed": 0, "expired_removed": 0}

    # Its own loop: `asyncio.sleep` is patched for the whole module while this runs.
    monkeypatch.setattr(app_module.asyncio, "sleep", one_pass)
    asyncio.run(audio_cleanup_task(Sessions(), store))

    assert not expired.exists()
    assert fresh.exists()
