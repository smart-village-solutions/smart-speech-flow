import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tenant-isolation-smoke.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("tenant_isolation_smoke", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_proves_both_positive_and_cross_tenant_paths_without_leaking_tokens(capsys):
    smoke = _load_script()
    settings = smoke.SmokeSettings(
        base_url="https://dialog.example",
        tenant_a_token="secret-token-a",
        tenant_b_token="secret-token-b",
    )
    terminated: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization")
        if request.method == "POST" and request.url.path == "/api/admin/session/create":
            session_id = "AAAA0001" if authorization == "Bearer secret-token-a" else "BBBB0001"
            return httpx.Response(201, json={"session_id": session_id})
        if request.method == "GET" and request.url.path.startswith("/api/admin/session/"):
            own = (
                authorization == "Bearer secret-token-a" and "AAAA0001" in request.url.path
            ) or (
                authorization == "Bearer secret-token-b" and "BBBB0001" in request.url.path
            )
            return httpx.Response(
                200 if own else 404,
                json={"status": "pending"} if own else {"detail": "Session not found"},
            )
        if request.method == "GET" and request.url.path.startswith("/api/customer/session/"):
            return httpx.Response(200, json={"status": "pending"})
        if request.method == "DELETE":
            terminated.append(request.url.path)
            return httpx.Response(200, json={"status": "terminated"})
        return httpx.Response(500)

    smoke.run_smoke(settings, transport=httpx.MockTransport(handler))

    captured = capsys.readouterr()
    assert captured.out.strip() == "Tenant isolation smoke passed"
    assert "secret-token" not in captured.out + captured.err
    assert terminated == [
        "/api/admin/session/AAAA0001/terminate",
        "/api/admin/session/BBBB0001/terminate",
    ]


def test_smoke_requires_all_credentials_without_echoing_them(monkeypatch, capsys):
    smoke = _load_script()
    monkeypatch.setenv("SSF_TENANT_A_TOKEN", "only-token")
    monkeypatch.delenv("SSF_TENANT_B_TOKEN", raising=False)
    monkeypatch.setenv("SSF_SMOKE_BASE_URL", "https://dialog.example")

    with pytest.raises(ValueError, match="Missing required smoke configuration"):
        smoke.SmokeSettings.from_environment()

    assert "only-token" not in capsys.readouterr().err


def test_smoke_cleans_up_a_partial_run_without_leaking_credentials(capsys):
    smoke = _load_script()
    settings = smoke.SmokeSettings(
        base_url="https://dialog.example",
        tenant_a_token="secret-token-a",
        tenant_b_token="secret-token-b",
    )
    requests: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization")
        requests.append((request.method, request.url.path, authorization))
        if request.method == "POST" and authorization == "Bearer secret-token-a":
            return httpx.Response(201, json={"session_id": "AAAA0001"})
        if request.method == "POST":
            return httpx.Response(503)
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "terminated"})
        return httpx.Response(500)

    with pytest.raises(smoke.SmokeFailure, match="Session creation failed"):
        smoke.run_smoke(settings, transport=httpx.MockTransport(handler))

    assert ("DELETE", "/api/admin/session/AAAA0001/terminate", "Bearer secret-token-a") in requests
    captured = capsys.readouterr()
    assert "secret-token" not in captured.out + captured.err
