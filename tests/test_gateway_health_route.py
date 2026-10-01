"""The public /health route names unreachable services without their internals (#230)."""

from __future__ import annotations

import importlib

import pytest
import requests

# routes/__init__.py re-exports the handler under the module's name; import by path.
health_route = importlib.import_module("services.api_gateway.routes.health")


def test_an_unreachable_service_is_named_without_its_host_or_port(monkeypatch):
    def refuse(url, timeout):
        raise requests.ConnectionError(
            f"HTTPConnectionPool(host='speech-internal', port=8000): {url}"
        )

    monkeypatch.setattr(health_route.requests, "get", refuse)

    result = health_route.health()

    assert set(result["services"].values()) == {"nicht erreichbar"}
    assert "speech-internal" not in str(result)


def test_an_error_that_is_not_a_request_failure_is_not_hidden(monkeypatch):
    def broken(url, timeout):
        raise KeyError("bug")

    monkeypatch.setattr(health_route.requests, "get", broken)

    with pytest.raises(KeyError):
        health_route.health()
