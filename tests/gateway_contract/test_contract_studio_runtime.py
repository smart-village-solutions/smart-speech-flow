"""Studio runtime configuration: fail-closed resolution and its HTTP mapping."""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import TENANT_A, TENANT_B, runtime_configuration

NO_ACTIVE_SESSION = {"detail": "Keine aktive Admin-Session gefunden"}


def test_session_create_resolves_the_signed_tenant_with_the_callers_correlation_id(client, studio):
    created = client.post("/api/admin/session/create", headers={"X-Correlation-Id": "trace-228"})

    assert created.status_code == 201
    assert studio.fetches == [(TENANT_A, "trace-228")]


@pytest.mark.parametrize(
    ("code", "retryable", "status_code"),
    [
        ("runtime_configuration_unavailable", True, 503),
        ("studio_runtime_network_error", True, 503),
        ("tenant_suspended", False, 502),
        ("tenant_not_found", False, 502),
        ("studio_runtime_response_invalid", False, 502),
    ],
)
def test_session_create_fails_closed_on_a_studio_failure(
    client, studio, code, retryable, status_code
):
    studio.fail(code, retryable=retryable)

    response = client.post("/api/admin/session/create")

    assert response.status_code == status_code
    assert response.json() == {"detail": code}
    assert client.get("/api/admin/session/current").json() == NO_ACTIVE_SESSION


def test_session_create_refuses_a_configuration_for_another_tenant(client, studio):
    studio.configuration_override = runtime_configuration(TENANT_B)

    response = client.post("/api/admin/session/create")

    assert response.status_code == 502
    assert response.json() == {"detail": "studio_runtime_tenant_mismatch"}
    assert client.get("/api/admin/session/current").json() == NO_ACTIVE_SESSION


def test_session_create_refuses_a_stale_authorization_revision(client, studio):
    configuration = runtime_configuration(TENANT_A).model_dump(by_alias=True)
    configuration["authorizationRevision"] = f"sha256:{'b' * 64}"
    studio.configuration_override = type(runtime_configuration(TENANT_A)).model_validate(
        configuration
    )

    response = client.post("/api/admin/session/create")

    assert response.status_code == 502
    assert response.json() == {"detail": "studio_runtime_authorization_mismatch"}


@pytest.mark.usefixtures("studio_unconfigured")
def test_session_create_without_studio_settings_is_a_bad_gateway(client):
    response = client.post("/api/admin/session/create")

    assert response.status_code == 502
    assert response.json() == {"detail": "studio_runtime_configuration_invalid"}


def test_session_create_refuses_a_malformed_correlation_id(client, studio):
    response = client.post("/api/admin/session/create", headers={"X-Correlation-Id": "a" * 129})

    assert response.status_code == 400
    assert response.json() == {"detail": "A valid X-Correlation-Id is required when supplied"}
    assert studio.fetches == []


@pytest.mark.parametrize(
    "code", ["tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"]
)
@pytest.mark.parametrize("retryable", [False, True])
def test_activation_is_refused_while_the_tenant_may_not_start_a_session(
    client, conversations, studio, code, retryable
):
    session_id = conversations.create()
    studio.fail(code, retryable=retryable)

    response = client.post(
        "/api/customer/session/activate", json={"session_id": session_id, "customer_language": "en"}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": code}
    assert client.get(f"/api/customer/session/{session_id}").json()["status"] == "pending"


@pytest.mark.parametrize(
    ("code", "retryable"),
    [("tenant_not_found", False), ("runtime_configuration_unavailable", True)],
)
def test_activation_proceeds_when_the_storage_policy_cannot_be_read(
    conversations, studio, code, retryable
):
    session_id = conversations.create()
    studio.fail(code, retryable=retryable)

    activated = conversations.activate(session_id, "en", consent=True)

    assert activated["status"] == "active"


def test_activation_without_studio_settings_still_activates(conversations):
    session_id = conversations.create()

    assert conversations.activate(session_id, "en", consent=True)["status"] == "active"
