"""Public API tests for the browser-safe Studio tenant directory."""

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.api_gateway.studio_login_directory as directory_module
from services.api_gateway.routes import login
from services.api_gateway.studio_login_directory import (
    StudioLoginDirectoryConfigurationError,
    get_studio_login_directory_service,
)
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectory,
    StudioLoginDirectoryClientError,
)
from services.api_gateway.studio_runtime_token import StudioTokenError

REVISION = f"sha256:{'a' * 64}"


def directory(*, empty: bool = False) -> StudioLoginDirectory:
    return StudioLoginDirectory.model_validate(
        {
            "contractVersion": "1.0",
            "directoryRevision": REVISION,
            "tenants": (
                []
                if empty
                else [
                    {
                        "id": "tenant-kassel",
                        "displayName": "Stadt Kassel",
                        "realm": "kassel-ssf-2025",
                        "privateStudioField": "must-not-leak",
                    }
                ]
            ),
            "privateDirectoryField": "must-not-leak",
        }
    )


class StubDirectoryService:
    def __init__(self, outcome: StudioLoginDirectory | Exception) -> None:
        self.outcome = outcome
        self.correlation_ids: list[str] = []

    async def get(self, correlation_id: str) -> StudioLoginDirectory:
        self.correlation_ids.append(correlation_id)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def route_client(service: StubDirectoryService) -> TestClient:
    app = FastAPI()
    app.include_router(login.router)
    app.dependency_overrides[get_studio_login_directory_service] = lambda: service
    return TestClient(app)


def test_returns_only_browser_safe_tenant_fields_without_authorization() -> None:
    service = StubDirectoryService(directory())

    response = route_client(service).get(
        "/api/login/tenants",
        headers={"X-Correlation-Id": "correlation-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenants": [
            {
                "id": "tenant-kassel",
                "displayName": "Stadt Kassel",
                "realm": "kassel-ssf-2025",
            }
        ]
    }
    assert service.correlation_ids == ["correlation-1"]


def test_generates_a_correlation_id_when_the_header_is_absent() -> None:
    service = StubDirectoryService(directory(empty=True))

    response = route_client(service).get("/api/login/tenants")

    assert response.status_code == 200
    assert response.json() == {"tenants": []}
    assert len(service.correlation_ids) == 1
    assert str(UUID(service.correlation_ids[0])) == service.correlation_ids[0]


@pytest.mark.parametrize("correlation_id", ["x" * 129, "correlation-\x7f"])
def test_rejects_a_malformed_correlation_id(correlation_id: str) -> None:
    service = StubDirectoryService(directory(empty=True))

    response = route_client(service).get(
        "/api/login/tenants",
        headers={"X-Correlation-Id": correlation_id},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "A valid X-Correlation-Id is required when supplied"}
    assert service.correlation_ids == []


@pytest.mark.parametrize(
    "failure",
    [
        StudioLoginDirectoryClientError("studio_login_directory_network_error", retryable=True),
        StudioTokenError("studio_token_network_error", retryable=True),
        StudioLoginDirectoryConfigurationError("studio_login_directory_configuration_invalid"),
    ],
)
def test_classified_directory_failures_return_the_same_neutral_503(
    failure: Exception,
) -> None:
    response = route_client(StubDirectoryService(failure)).get("/api/login/tenants")

    assert response.status_code == 503
    assert response.json() == {"detail": "The login directory is temporarily unavailable"}
    assert str(failure) not in response.text


def test_dependency_factory_converts_configuration_failures_to_neutral_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_build() -> None:
        raise StudioLoginDirectoryConfigurationError("studio_login_directory_configuration_invalid")

    monkeypatch.setattr(directory_module, "_build_studio_login_directory_service", fail_to_build)
    app = FastAPI()
    app.include_router(login.router)

    response = TestClient(app, raise_server_exceptions=False).get("/api/login/tenants")

    assert response.status_code == 503
    assert response.json() == {"detail": "The login directory is temporarily unavailable"}


def test_production_app_registers_the_login_directory_as_a_public_route() -> None:
    from services.api_gateway.app import app

    response = TestClient(app, raise_server_exceptions=False).get("/api/login/tenants")

    assert response.status_code == 503
    assert response.json() == {"detail": "The login directory is temporarily unavailable"}
