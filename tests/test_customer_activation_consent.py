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
def client(request: pytest.FixtureRequest) -> TestClient:
    session_manager.reset(clear_persistence=True)
    return TestClient(app, client=(request.node.nodeid, 50000))


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

@pytest.mark.parametrize("authenticated", [False, True], ids=["guest", "user"])
@pytest.mark.parametrize("selector_source", ["body", "nested_body", "query", "header", "cookie"])
def test_activation_rejects_tenant_selectors_before_mutation(
    pending_session, client, studio, monkeypatch, authenticated, selector_source
):
    from services.api_gateway.auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user

    session_id, key = pending_session
    principal = {VERIFIED_TENANT_ID_CLAIM: key.tenant_id} if authenticated else None
    monkeypatch.setitem(app.dependency_overrides, optional_ssf_user, lambda: principal)
    payload = {"session_id": session_id, "customer_language": "en"}
    options = {}
    if selector_source == "body":
        payload["tenant_id"] = "other-tenant"
    elif selector_source == "nested_body":
        payload["extra"] = [{"studio_tenant_id": "other-tenant"}]
    elif selector_source == "query":
        options["params"] = {"tenantId": "other-tenant"}
    elif selector_source == "header":
        options["headers"] = {"X-Studio-Tenant-Id": "other-tenant"}
    else:
        client.cookies.set("studio_tenant_id", "other-tenant")

    response = client.post("/api/customer/session/activate", json=payload, **options)

    assert response.status_code == 400
    assert session_manager.get_session(key).status.value == "pending"
    assert session_manager.get_session(key).customer_language is None
    assert studio.calls == 0


@pytest.mark.parametrize("actor", [None, "tenant-test", "other-tenant"])
def test_activation_preserves_guest_and_authenticated_tenant_access(
    pending_session, client, studio, monkeypatch, actor
):
    from services.api_gateway.auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user

    session_id, key = pending_session
    principal = {VERIFIED_TENANT_ID_CLAIM: actor} if actor else None
    monkeypatch.setitem(app.dependency_overrides, optional_ssf_user, lambda: principal)

    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )

    assert response.status_code == (404 if actor == "other-tenant" else 200)
    assert session_manager.get_session(key).status.value == (
        "pending" if actor == "other-tenant" else "active"
    )


@pytest.mark.parametrize("authenticated", [False, True], ids=["guest", "user"])
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", ""),
        ("GET", "/messages"),
        ("POST", "/message"),
        ("GET", "/audio/missing/original.wav"),
    ],
)
def test_customer_session_routes_reject_query_tenant_selectors(
    pending_session, client, monkeypatch, authenticated, method, suffix
):
    from services.api_gateway.auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user

    session_id, key = pending_session
    principal = {VERIFIED_TENANT_ID_CLAIM: key.tenant_id} if authenticated else None
    monkeypatch.setitem(app.dependency_overrides, optional_ssf_user, lambda: principal)

    response = client.request(
        method,
        f"/api/customer/session/{session_id}{suffix}",
        params={"tenant_id": "other-tenant"},
    )

    assert response.status_code == 400
    assert session_manager.get_session(key).status.value == "pending"
