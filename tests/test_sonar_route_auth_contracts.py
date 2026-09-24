"""Behavior contracts for the gateway route and authentication cleanup."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

import services.api_gateway.app as gateway
from services.api_gateway.realtime_ticket import (
    CONSUME_TICKET_LUA,
    MemoryRealtimeTicketBackend,
    RealtimeTicketStore,
)
from services.api_gateway.routes import admin, customer
from services.api_gateway.session_manager import session_manager
from services.api_gateway.studio_login_directory_client import DirectoryTransport
from services.api_gateway.tenant_session import TenantSessionKey


async def _wait_until_cancelled(*_args: object) -> None:
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_lifespan_reports_a_background_task_failure_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    """A completed task failure remains visible while shutdown continues."""

    async def first_failure(*_collaborators: object) -> None:
        raise RuntimeError("first background task failed")

    async def second_failure(*_collaborators: object) -> None:
        raise RuntimeError("second background task failed")

    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(gateway, "session_timeout_monitor", first_failure)
    monkeypatch.setattr(gateway, "circuit_breaker_monitor", second_failure)
    for task_name in (
        "websocket_monitor_task",
        "websocket_fallback_task",
        "audio_cleanup_task",
        "feedback_maintenance_task",
        "feedback_connect_task",
    ):
        monkeypatch.setattr(gateway, task_name, _wait_until_cancelled)

    async with gateway.lifespan(gateway.app):
        await asyncio.sleep(0)

    diagnostics = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Background task shutdown error:")
    ]
    assert diagnostics == [
        "Background task shutdown error: first background task failed",
        "Background task shutdown error: second background task failed",
    ]


@pytest.mark.parametrize(
    ("script", "number_of_keys"),
    [
        pytest.param("return nil", 1, id="unexpected-script"),
        pytest.param(CONSUME_TICKET_LUA, 2, id="unexpected-key-count"),
    ],
)
def test_memory_ticket_backend_rejects_invalid_eval_without_consuming_ticket(
    script: str, number_of_keys: int
) -> None:
    """A rejected Redis contract must leave the single-use ticket available."""
    backend = MemoryRealtimeTicketBackend()
    store = RealtimeTicketStore(backend)
    session_key = TenantSessionKey("tenant-test", "ABC12345")
    issued = store.issue(session_key, "websocket")
    stored_ticket_key = next(iter(backend.values))

    with pytest.raises(ValueError, match="unsupported realtime ticket script"):
        backend.eval(script, number_of_keys, stored_ticket_key)

    assert store.consume(issued.ticket, session_key, "websocket") is True
    assert store.consume(issued.ticket, session_key, "websocket") is False


@pytest.mark.asyncio
async def test_unimplemented_directory_transport_fails_explicitly() -> None:
    """An inherited protocol stub must not silently look like a response."""

    class UnimplementedTransport(DirectoryTransport):
        pass

    transport = UnimplementedTransport()
    url = "https://studio.test"
    headers: dict[str, str] = {}
    timeout_seconds = 1.0

    with pytest.raises(NotImplementedError):
        await transport.get(url, headers, timeout_seconds)


@pytest.mark.asyncio
async def test_feedback_connection_failure_is_reported_and_retried(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transient wiring failure must not stop the feedback retry loop."""
    delays: list[int] = []
    wiring_attempts = 0

    async def record_delay(delay: int) -> None:
        delays.append(delay)

    async def wire_feedback(*_args: object) -> bool:
        nonlocal wiring_attempts
        wiring_attempts += 1
        if wiring_attempts == 1:
            raise RuntimeError("database unavailable")
        return True

    monkeypatch.setattr(gateway.asyncio, "sleep", record_delay)
    monkeypatch.setattr(gateway, "_wire_feedback", wire_feedback)

    state = SimpleNamespace()
    sessions = object()
    await gateway.feedback_connect_task(
        state,
        "postgresql://request",
        "postgresql://maintenance",
        sessions,
        "postgresql://reader",
    )

    assert wiring_attempts == 2
    assert delays == [5, 10]
    assert capsys.readouterr().out.splitlines() == [
        "⚠️ Feedback connection attempt failed: RuntimeError"
    ]


@pytest.mark.asyncio
async def test_feedback_maintenance_failure_is_reported_and_next_pass_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed maintenance pass must not prevent the next reconciliation."""

    class RecoveringMaintenance:
        def __init__(self) -> None:
            self.reconciliation_attempts = 0

        async def reconcile_once(self) -> None:
            self.reconciliation_attempts += 1
            if self.reconciliation_attempts == 1:
                raise RuntimeError("reconciliation unavailable")

        async def expire_once(self) -> None:
            raise AssertionError("retention should not run during this scenario")

    sleep_calls = 0

    async def run_two_passes(_delay: int) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(gateway.asyncio, "sleep", run_two_passes)
    maintenance = RecoveringMaintenance()
    state = SimpleNamespace(feedback_maintenance=maintenance)

    with pytest.raises(asyncio.CancelledError):
        await gateway.feedback_maintenance_task(state)

    assert maintenance.reconciliation_attempts == 2
    assert capsys.readouterr().out.splitlines() == [
        "⚠️ Feedback maintenance pass failed: RuntimeError"
    ]


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(admin.terminate_session, id="terminate"),
        pytest.param(admin.get_session_status, id="status"),
    ],
)
@pytest.mark.asyncio
async def test_admin_session_routes_return_not_found_after_session_disappears(
    handler,
) -> None:
    """Admin session operations must preserve the public 404 race contract."""
    session_id = "MISSING1"
    key = TenantSessionKey("tenant-test", session_id)

    with pytest.raises(HTTPException) as caught:
        await handler(session_id, key, session_manager)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


@pytest.mark.asyncio
async def test_customer_status_returns_not_found_after_session_disappears() -> None:
    """Customer status must preserve the public 404 race contract."""
    session_id = "MISSING2"
    key = TenantSessionKey("tenant-test", session_id)

    with pytest.raises(HTTPException) as caught:
        await customer.get_customer_session_status(session_id, key, session_manager)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


@pytest.mark.asyncio
async def test_customer_activation_returns_not_found_after_session_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activation must return 404 if a resolved session disappears before use."""
    session_id = "MISSING3"
    key = TenantSessionKey("tenant-test", session_id)
    activation = customer.ActivateSessionRequest(
        session_id=session_id,
        customer_language="en",
    )
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(
        customer,
        "require_customer_session_key",
        lambda _session_id, _principal, _sessions: key,
    )

    with pytest.raises(HTTPException) as caught:
        await customer.activate_session(activation, request, None, session_manager, None)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


def test_affected_routes_keep_their_response_schemas_and_query_contracts() -> None:
    """Annotation cleanup must leave the generated public contract unchanged."""
    schema = gateway.app.openapi()
    expected_response_models = {
        (
            "/api/admin/session/{session_id}/realtime-ticket",
            "post",
            "200",
        ): "RealtimeTicketResponse",
        ("/api/feedback", "post", "201"): "FeedbackAcceptedResponse",
        ("/api/feedback", "get", "200"): "FeedbackListResponse",
        ("/api/feedback/{feedback_id}", "get", "200"): "FeedbackDetailResponse",
        ("/api/login/tenants", "get", "200"): "LoginTenantDirectoryResponse",
    }

    for (path, method, status_code), model_name in expected_response_models.items():
        response_schema = schema["paths"][path][method]["responses"][status_code]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    feedback_parameters = schema["paths"]["/api/feedback"]["get"]["parameters"]
    assert feedback_parameters == [
        {
            "name": "limit",
            "in": "query",
            "required": False,
            "schema": {
                "type": "integer",
                "maximum": 200,
                "minimum": 1,
                "default": 50,
                "title": "Limit",
            },
        },
        {
            "name": "offset",
            "in": "query",
            "required": False,
            "schema": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "title": "Offset",
            },
        },
    ]
