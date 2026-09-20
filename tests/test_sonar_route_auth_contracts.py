"""Behavior contracts for the gateway route and authentication cleanup."""

import asyncio

import pytest

import services.api_gateway.app as gateway
from services.api_gateway.realtime_ticket import (
    CONSUME_TICKET_LUA,
    MemoryRealtimeTicketBackend,
    RealtimeTicketStore,
)
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

    async def first_failure() -> None:
        raise RuntimeError("first background task failed")

    async def second_failure() -> None:
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

    with pytest.raises(NotImplementedError):
        await UnimplementedTransport().get("https://studio.test", {}, 1.0)


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
