"""The legacy one-shot routes are gone, not merely unlinked (#230)."""

from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from tests.gateway_contract.contract_support import wav_bytes


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/pipeline"), ("post", "/upload"), ("get", "/")],
)
def test_a_legacy_route_answers_404_and_reaches_no_speech_service(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    speech_calls: list[str] = []

    def record(url: str, **_options: Any) -> None:
        speech_calls.append(url)
        raise AssertionError(f"speech service reached: {url}")

    monkeypatch.setattr(requests, "post", record)
    with TestClient(app) as client:
        if method == "post":
            response = client.post(
                path,
                files={"file": ("speech.wav", wav_bytes(1.0), "audio/wav")},
                data={"source_lang": "de", "target_lang": "en"},
            )
        else:
            response = client.get(path)

    assert response.status_code == 404
    assert speech_calls == []
