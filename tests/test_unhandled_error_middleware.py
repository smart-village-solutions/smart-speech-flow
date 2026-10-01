"""An unhandled route error: JSON 500 with CORS, and a log without its message (#230)."""

from __future__ import annotations

import traceback

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.api_gateway.app import create_app
from services.api_gateway.log_safety import RedactedServerError

ORIGIN = "https://translate.smart-village.solutions"
SECRET = "session-secret-4711"


def _app_with_test_routes() -> FastAPI:
    app = create_app()

    @app.get("/__crash")
    async def crash() -> None:
        raise KeyError(SECRET)

    @app.get("/__not_found")
    async def not_found() -> None:
        raise HTTPException(status_code=404, detail="nothing here")

    return app


def test_a_crash_answers_json_500_with_cors_headers():
    client = TestClient(_app_with_test_routes(), raise_server_exceptions=False)

    response = client.get("/__crash", headers={"Origin": ORIGIN})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert SECRET not in response.text


def test_the_crash_is_re_raised_with_only_its_type_name():
    client = TestClient(_app_with_test_routes())

    with pytest.raises(RedactedServerError) as raised:
        client.get("/__crash")

    assert str(raised.value) == "KeyError"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_the_formatted_traceback_keeps_frames_and_type_but_not_the_message():
    client = TestClient(_app_with_test_routes())

    with pytest.raises(RedactedServerError) as raised:
        client.get("/__crash")

    text = "".join(traceback.format_exception(raised.value))
    assert "in crash" in text
    assert "KeyError" in text
    assert SECRET not in text


def test_an_http_exception_reaches_the_client_unchanged():
    client = TestClient(_app_with_test_routes())

    response = client.get("/__not_found", headers={"Origin": ORIGIN})

    assert response.status_code == 404
    assert response.json() == {"detail": "nothing here"}
    assert response.headers["access-control-allow-origin"] == ORIGIN
