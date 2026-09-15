"""Configured production frontend origins must match exactly in HTTP and WS."""

import importlib

import pytest
from starlette.middleware.cors import CORSMiddleware

from services.api_gateway.client_origin import configured_client_origin
from services.api_gateway.websocket import validate_websocket_origin


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://dialog.kassel.de",
        "https://*.kassel.de",
        "https://user:password@dialog.kassel.de",
        "https://dialog.kassel.de/path",
        "https://dialog.kassel.de?query",
        "https://dialog.kassel.de#fragment",
        "https://dialog.kassel.de:99999",
        "https://dialog.kassel.de:bad",
        "https://[invalid",
        "https://dia\tlog.kassel.de",
    ],
)
def test_invalid_client_origin_is_not_allowed(monkeypatch, value):
    monkeypatch.setenv("CLIENT_BASE_URL", value)
    assert configured_client_origin() is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Dialog.Kassel.de/", "https://dialog.kassel.de"),
        ("https://dialog.kassel.de:443", "https://dialog.kassel.de"),
        ("https://dialog.kassel.de:8443", "https://dialog.kassel.de:8443"),
    ],
)
def test_client_origin_normalization(monkeypatch, value, expected):
    monkeypatch.setenv("CLIENT_BASE_URL", value)
    assert configured_client_origin() == expected


@pytest.mark.asyncio
async def test_production_http_and_websocket_use_exact_configured_origin(monkeypatch):
    app_module = importlib.import_module("services.api_gateway.app")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_BASE_URL", "https://dialog.kassel.de/")
    captured = {}
    monkeypatch.setattr(
        app_module.app, "add_middleware", lambda cls, **kwargs: captured.update(kwargs)
    )
    app_module.setup_cors_for_websockets()
    cors = CORSMiddleware(app_module.app, **captured)
    for origin, allowed in [
        ("https://dialog.kassel.de", True),
        ("https://translate.smart-village.solutions", True),
        ("https://evil.dialog.kassel.de", False),
        ("https://dialog.kassel.de.evil.invalid", False),
        ("https://translate.smart-village.solutions.evil.invalid", False),
        ("https://example.figma.site.evil.invalid", False),
        ("https://dialog.kassel.de:8443", False),
        ("http://dialog.kassel.de", False),
    ]:
        assert cors.is_allowed_origin(origin) is allowed
        assert await validate_websocket_origin(origin) is allowed
    assert await validate_websocket_origin(None) is False


@pytest.mark.asyncio
async def test_unconfigured_origin_keeps_existing_production_defaults(monkeypatch):
    app_module = importlib.import_module("services.api_gateway.app")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CLIENT_BASE_URL", raising=False)
    captured = {}
    monkeypatch.setattr(
        app_module.app, "add_middleware", lambda cls, **kwargs: captured.update(kwargs)
    )
    app_module.setup_cors_for_websockets()
    cors = CORSMiddleware(app_module.app, **captured)
    assert not cors.is_allowed_origin("https://dialog.kassel.de")
    assert not await validate_websocket_origin("https://dialog.kassel.de")
    assert cors.is_allowed_origin("https://translate.smart-village.solutions")
    assert await validate_websocket_origin("https://translate.smart-village.solutions")


@pytest.mark.asyncio
async def test_existing_websocket_subdomain_policy_is_preserved(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CLIENT_BASE_URL", raising=False)
    assert await validate_websocket_origin("https://existing.smart-village.solutions")
    assert not await validate_websocket_origin(
        "https://existing.smart-village.solutions.evil.invalid"
    )
