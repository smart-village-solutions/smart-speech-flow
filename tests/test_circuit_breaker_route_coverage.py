from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.routes import circuit_breaker


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(circuit_breaker.router, prefix="/api")
    return TestClient(app)


def _circuit(state="closed", health_status=None):
    circuit = MagicMock()
    circuit.state = SimpleNamespace(value=state)
    circuit.get_health_status.return_value = health_status or {"state": state}
    return circuit


def test_services_health_returns_monitoring_timestamp(client, monkeypatch):
    health_status = {
        "monitoring_info": {"last_check": "2026-07-20T10:00:00Z"},
        "overall_healthy": True,
    }
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_health_status",
        AsyncMock(return_value=health_status),
    )

    response = client.get("/api/health/services")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": health_status,
        "timestamp": "2026-07-20T10:00:00Z",
    }


def test_services_health_converts_client_failure_to_server_error(client, monkeypatch):
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_health_status",
        AsyncMock(side_effect=RuntimeError("upstream unavailable")),
    )

    response = client.get("/api/health/services")

    assert response.status_code == 500
    assert response.json()["detail"] == "Health status check failed: upstream unavailable"


def test_single_service_health_validates_name_and_handles_missing_service(
    client, monkeypatch
):
    invalid_response = client.get("/api/health/services/unknown")
    assert invalid_response.status_code == 400
    assert "Valid services: asr, translation, tts" in invalid_response.json()["detail"]

    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_service_status",
        AsyncMock(return_value=None),
    )
    missing_response = client.get("/api/health/services/asr")

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Service 'asr' not found or not registered"


def test_single_service_health_returns_status_and_wraps_client_error(client, monkeypatch):
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_service_status",
        AsyncMock(return_value={"healthy": True}),
    )

    success_response = client.get("/api/health/services/tts")

    assert success_response.status_code == 200
    assert success_response.json()["data"] == {"healthy": True}

    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_service_status",
        AsyncMock(side_effect=RuntimeError("monitor failed")),
    )
    error_response = client.get("/api/health/services/tts")

    assert error_response.status_code == 500
    assert error_response.json()["detail"] == "Service health check failed: monitor failed"


def test_circuit_breaker_status_lists_each_circuit_and_handles_factory_error(
    client, monkeypatch
):
    circuits = {"asr": _circuit("open"), "tts": _circuit("closed")}
    monkeypatch.setattr(
        circuit_breaker.CircuitBreakerFactory, "get_all_circuits", lambda: circuits
    )

    success_response = client.get("/api/health/circuit-breakers")

    assert success_response.status_code == 200
    assert success_response.json()["total_circuits"] == 2
    assert success_response.json()["circuits"] == {
        "asr": {"state": "open"},
        "tts": {"state": "closed"},
    }

    monkeypatch.setattr(
        circuit_breaker.CircuitBreakerFactory,
        "get_all_circuits",
        MagicMock(side_effect=RuntimeError("registry failed")),
    )
    error_response = client.get("/api/health/circuit-breakers")

    assert error_response.status_code == 500
    assert error_response.json()["detail"] == "Circuit breaker status check failed: registry failed"


def test_degradation_status_returns_client_data_and_wraps_errors(client, monkeypatch):
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_degradation_status",
        AsyncMock(return_value={"current_mode": "degraded"}),
    )

    success_response = client.get("/api/health/degradation")
    assert success_response.status_code == 200
    assert success_response.json()["data"] == {"current_mode": "degraded"}

    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_degradation_status",
        AsyncMock(side_effect=RuntimeError("degradation unavailable")),
    )
    error_response = client.get("/api/health/degradation")

    assert error_response.status_code == 500
    assert error_response.json()["detail"] == (
        "Degradation status check failed: degradation unavailable"
    )


def test_reset_one_circuit_validates_service_and_returns_state_transition(
    client, monkeypatch
):
    invalid_response = client.post("/api/admin/circuit-breakers/invalid/reset")
    assert invalid_response.status_code == 400

    asr_circuit = _circuit("open")
    monkeypatch.setattr(
        circuit_breaker.CircuitBreakerFactory,
        "get_all_circuits",
        lambda: {"asr": asr_circuit},
    )
    success_response = client.post("/api/admin/circuit-breakers/asr/reset")

    assert success_response.status_code == 200
    assert success_response.json()["old_state"] == "open"
    assert success_response.json()["new_state"] == "closed"
    asr_circuit.reset.assert_called_once_with()

    missing_response = client.post("/api/admin/circuit-breakers/tts/reset")
    assert missing_response.status_code == 404


def test_reset_all_circuits_and_wraps_reset_failure(client, monkeypatch):
    circuits = {"asr": _circuit("open"), "translation": _circuit("half_open")}
    monkeypatch.setattr(
        circuit_breaker.CircuitBreakerFactory, "get_all_circuits", lambda: circuits
    )

    success_response = client.post("/api/admin/circuit-breakers/reset-all")

    assert success_response.status_code == 200
    assert success_response.json()["results"] == {
        "asr": {"old_state": "open", "new_state": "closed"},
        "translation": {"old_state": "half_open", "new_state": "closed"},
    }

    circuits["translation"].reset.side_effect = RuntimeError("reset failed")
    error_response = client.post("/api/admin/circuit-breakers/reset-all")

    assert error_response.status_code == 500
    assert error_response.json()["detail"] == "Circuit breakers reset failed: reset failed"


def test_cache_routes_return_status_and_clear_cache(client, monkeypatch):
    manager = MagicMock()
    manager.get_degradation_status.return_value = {
        "cache_size": 4,
        "cache_stats": {"hits": 3},
        "pending_requests": 2,
        "current_mode": "full",
    }
    monkeypatch.setattr(circuit_breaker, "graceful_degradation_manager", manager)

    status_response = client.get("/api/health/cache")
    clear_response = client.delete("/api/admin/cache/clear")

    assert status_response.status_code == 200
    assert status_response.json()["data"]["cache_size"] == 4
    assert clear_response.status_code == 200
    assert clear_response.json()["entries_removed"] == 4
    manager.response_cache.clear.assert_called_once_with()
    assert manager.cache_stats == {"hits": 0, "misses": 0, "evictions": 0}


def test_health_summary_aggregates_alerts_and_wraps_failures(client, monkeypatch):
    health_status = {
        "overall_healthy": False,
        "summary": {"total": 3},
        "services": {"unhealthy": ["translation"]},
        "gpu_summary": {
            "alerts": [{"severity": "critical", "service": "asr", "device": 0, "message": "hot"}],
            "services_missing_gpu": ["tts"],
        },
    }
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_health_status",
        AsyncMock(return_value=health_status),
    )
    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_degradation_status",
        AsyncMock(return_value={"current_mode": "fallback", "cache_size": 801}),
    )
    monkeypatch.setattr(
        circuit_breaker.CircuitBreakerFactory,
        "get_all_circuits",
        lambda: {"asr": _circuit("open"), "tts": _circuit("half_open")},
    )

    success_response = client.get("/api/health/summary")

    assert success_response.status_code == 200
    alert_types = {alert["type"] for alert in success_response.json()["alerts"]}
    assert alert_types == {
        "service_down",
        "circuit_open",
        "circuit_testing",
        "degraded_mode",
        "cache_full",
        "gpu_pressure",
        "gpu_unavailable",
    }

    monkeypatch.setattr(
        circuit_breaker.circuit_breaker_client,
        "get_health_status",
        AsyncMock(side_effect=RuntimeError("summary unavailable")),
    )
    error_response = client.get("/api/health/summary")

    assert error_response.status_code == 500
    assert error_response.json()["detail"] == (
        "Health summary generation failed: summary unavailable"
    )
