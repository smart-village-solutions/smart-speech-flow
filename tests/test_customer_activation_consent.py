"""Activation resolves consent exactly once, from a live read."""

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.session_manager import session_manager
from services.api_gateway.studio_runtime_client import StudioRuntimeClientError
from tests.runtime_policy_helpers import configuration


class _FakeStudio:
    """Stand in for the composed runtime flow on the activation path.

    Named `calls` to match `RecordingClient` in `tests.runtime_policy_helpers`.
    """

    def __init__(self) -> None:
        self._mode = "ask"
        self._error: Exception | None = None
        self.calls = 0

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._error = None

    def fail(self, code: str, *, status: int | None = None, retryable: bool = True):
        self._error = StudioRuntimeClientError(code, retryable=retryable)

    def reset_calls(self) -> None:
        self.calls = 0

    # The flow exposes the client; the route reads through it.
    @property
    def client(self) -> "_FakeStudio":
        return self

    async def fetch(self, tenant_id: str, correlation_id: str):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return configuration(tenant_id=tenant_id, mode=self._mode)


@pytest.fixture
def studio(monkeypatch: pytest.MonkeyPatch) -> _FakeStudio:
    fake = _FakeStudio()
    monkeypatch.setattr(
        "services.api_gateway.routes.customer.runtime_flow_from_environment",
        lambda: fake,
    )
    return fake


@pytest.fixture
def client() -> TestClient:
    session_manager.reset(clear_persistence=True)
    return TestClient(app)


def _create_pending(client: TestClient):
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = session_manager.resolve_customer_session(session_id)
    assert key is not None
    return session_id, key


@pytest.fixture
def pending_session(client: TestClient):
    return _create_pending(client)


@pytest.fixture
def active_granted_session(client: TestClient, studio: _FakeStudio):
    session_id, key = _create_pending(client)
    studio.set_mode("ask")
    response = client.post(
        "/api/customer/session/activate",
        json={
            "session_id": session_id,
            "customer_language": "en",
            "data_retention_consent": True,
        },
    )
    assert response.status_code == 200
    assert session_manager.get_session(key).consent_status is ConsentStatus.GRANTED
    return session_id, key


def test_ask_mode_with_affirmative_answer_grants(pending_session, client, studio):
    session_id, key = pending_session
    studio.set_mode("ask")
    response = client.post(
        "/api/customer/session/activate",
        json={
            "session_id": session_id,
            "customer_language": "en",
            "data_retention_consent": True,
        },
    )
    assert response.status_code == 200
    assert session_manager.get_session(key).consent_status is ConsentStatus.GRANTED


def test_absent_answer_declines(pending_session, client, studio):
    session_id, key = pending_session
    studio.set_mode("ask")
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 200
    assert session_manager.get_session(key).consent_status is ConsentStatus.DECLINED


def test_disabled_mode_sets_policy_disabled(pending_session, client, studio):
    session_id, key = pending_session
    studio.set_mode("disabled")
    client.post(
        "/api/customer/session/activate",
        json={
            "session_id": session_id,
            "customer_language": "en",
            "data_retention_consent": True,
        },
    )
    assert (
        session_manager.get_session(key).consent_status
        is ConsentStatus.POLICY_DISABLED
    )


def test_failed_read_leaves_pending_and_still_activates(
    pending_session, client, studio
):
    session_id, key = pending_session
    studio.fail("runtime_configuration_unavailable", retryable=True)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 200
    session = session_manager.get_session(key)
    assert session.status.value == "active"
    assert session.consent_status is ConsentStatus.PENDING


@pytest.mark.parametrize(
    "code", ["tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"]
)
def test_conflict_refuses_activation(pending_session, client, studio, code):
    session_id, key = pending_session
    studio.fail(code, retryable=False)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 409
    session = session_manager.get_session(key)
    assert session.status.value == "pending"
    assert session.consent_status is ConsentStatus.PENDING


def test_language_change_does_not_re_resolve_consent(
    active_granted_session, client, studio
):
    session_id, key = active_granted_session
    studio.set_mode("ask")
    studio.reset_calls()
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "de"},
    )
    assert response.status_code == 200
    session = session_manager.get_session(key)
    assert session.customer_language == "de"
    assert session.consent_status is ConsentStatus.GRANTED
    assert studio.calls == 0


def test_language_change_succeeds_while_tenant_unavailable(
    active_granted_session, client, studio
):
    session_id, key = active_granted_session
    studio.fail("tenant_suspended", retryable=False)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "de"},
    )
    assert response.status_code == 200
    assert session_manager.get_session(key).consent_status is ConsentStatus.GRANTED


def test_activation_never_routes_through_the_policy_gate(
    pending_session, client, studio, monkeypatch
):
    # `RuntimePolicyGate.authorize` records discarded conversation content on
    # every refusal. Activation writes none, so no counter may move.
    async def _forbidden(*args, **kwargs):
        raise AssertionError("activation must not call the policy gate")

    monkeypatch.setattr(
        "services.api_gateway.runtime_policy.RuntimePolicyGate.authorize", _forbidden
    )
    session_id, key = pending_session
    studio.set_mode("disabled")
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 200
    assert (
        session_manager.get_session(key).consent_status
        is ConsentStatus.POLICY_DISABLED
    )
