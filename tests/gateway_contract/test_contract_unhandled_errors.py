"""A crash inside a real message route reaches the client only through the net (#230)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api_gateway import message_processing
from services.api_gateway.app import app
from services.api_gateway.log_safety import RedactedServerError

SECRET = "private-crash-detail"


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


@pytest.fixture
def crash_after_the_pipeline(monkeypatch):
    async def crash(**_arguments):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(message_processing, "create_session_message", crash)


@pytest.mark.usefixtures("speech_services", "crash_after_the_pipeline")
def test_the_client_gets_the_generic_json_500_and_nothing_is_stored(client, active_session):
    # The same app and rate-limit bucket, answering the crash instead of raising it.
    browser = TestClient(app, raise_server_exceptions=False, headers=dict(client.headers))

    response = browser.post(
        f"/api/admin/session/{active_session}/message",
        json={"text": "Guten Tag", "source_lang": "de", "target_lang": "en"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert SECRET not in response.text
    history = client.get(f"/api/admin/session/{active_session}/messages")
    assert history.json()["messages"] == []


@pytest.mark.usefixtures("speech_services", "crash_after_the_pipeline")
def test_the_server_sees_the_crash_redacted(conversations, active_session):
    with pytest.raises(RedactedServerError) as raised:
        conversations.send_text(active_session)

    assert str(raised.value) == "RuntimeError"
