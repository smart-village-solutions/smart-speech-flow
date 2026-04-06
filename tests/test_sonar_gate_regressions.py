import asyncio
import importlib

from fastapi.testclient import TestClient

from services.api_gateway.app import app


client = TestClient(app)


def test_public_languages_endpoint_matches_api_languages_endpoint():
    public_response = client.get("/languages")
    api_response = client.get("/api/languages/supported")

    assert public_response.status_code == 200
    assert api_response.status_code == 200
    assert public_response.json() == api_response.json()


def test_service_health_gpu_summary_recommends_review_for_warning_only():
    service_health = importlib.import_module("services.api_gateway.service_health")
    manager = service_health.ServiceHealthManager()

    manager.service_status["asr"].resources = {
        "gpu": {
            "available": True,
            "devices": [
                {
                    "device_index": 0,
                    "utilization_percent": 80.0,
                    "memory_utilization": 40.0,
                    "temperature_c": 50,
                }
            ],
        }
    }

    summary = manager.get_gpu_summary()

    assert summary["warning_devices"] == 1
    assert summary["critical_devices"] == 0
    assert summary["scale_up_recommendations"] == 0
    assert summary["recommended_action"] == "review"


async def _raise_cancelled_error():
    raise asyncio.CancelledError()


class _CancelledTask:
    def __init__(self):
        self.cancel_called = False

    def cancel(self):
        self.cancel_called = True

    def __await__(self):
        return _raise_cancelled_error().__await__()


class _ClosableSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


async def test_service_health_stop_monitoring_closes_cancelled_task():
    service_health = importlib.import_module("services.api_gateway.service_health")
    manager = service_health.ServiceHealthManager()
    task = _CancelledTask()
    session = _ClosableSession()

    manager.is_monitoring = True
    manager.health_check_task = task
    manager.session = session

    await manager.stop_monitoring()

    assert task.cancel_called is True
    assert session.closed is True
    assert manager.is_monitoring is False
    assert manager.health_check_task is None
    assert manager.session is None
