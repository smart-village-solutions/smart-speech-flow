"""Activation resolves consent exactly once, from a live read."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.dependencies import get_studio_runtime_flow
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from tests.runtime_policy_helpers import REVISION, runtime_read

OTHER_REVISION = f"sha256:{'b' * 64}"
_KASSEL_FIXTURE = Path(__file__).parent / "fixtures" / "studio_v2" / "runtime-tenant-kassel.json"


class _FakeStudio:
    """Stand in for the composed runtime flow on the activation path.

    Named `calls` to match `RecordingClient` in `tests.runtime_policy_helpers`.
    """

    def __init__(self) -> None:
        self._mode = "ask"
        self._error: Exception | None = None
        self.calls = 0
        self.retention_hours: int | None = 4320
        self.revision = REVISION

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._error = None

    def fail(self, code: str, *, status: int | None = None, retryable: bool = True):
        self._error = StudioRuntimeV2ClientError(code, retryable=retryable)

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
        if self._mode == "disabled":
            return runtime_read(tenant_id=tenant_id, mode="disabled", revision=self.revision)
        return runtime_read(
            tenant_id=tenant_id,
            mode="ask",
            retention_hours=self.retention_hours,
            revision=self.revision,
        )


@pytest.fixture
def studio(monkeypatch: pytest.MonkeyPatch) -> _FakeStudio:
    fake = _FakeStudio()
    monkeypatch.setitem(app.dependency_overrides, get_studio_runtime_flow, lambda: fake)
    return fake


@pytest.fixture
def client(session_manager, request: pytest.FixtureRequest) -> TestClient:
    session_manager.reset(clear_persistence=True)
    return TestClient(app, client=(request.node.nodeid, 50000))


async def _create_pending(client: TestClient, session_manager):
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = await session_manager.resolve_customer_session(session_id)
    assert key is not None
    return session_id, key


@pytest.fixture
async def pending_session(client: TestClient, session_manager):
    return await _create_pending(client, session_manager)


@pytest.fixture
async def active_granted_session(session_manager, client: TestClient, studio: _FakeStudio):
    session_id, key = await _create_pending(client, session_manager)
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
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.GRANTED
    return session_id, key


async def test_ask_mode_with_affirmative_answer_grants(session_manager, pending_session, client, studio):
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
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.GRANTED


async def test_absent_answer_declines(session_manager, pending_session, client, studio):
    session_id, key = pending_session
    studio.set_mode("ask")
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 200
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.DECLINED


async def test_disabled_mode_sets_policy_disabled(session_manager, pending_session, client, studio):
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
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.POLICY_DISABLED


async def test_failed_read_leaves_pending_and_still_activates(
    session_manager, pending_session, client, studio
):
    session_id, key = pending_session
    studio.fail("runtime_configuration_unavailable", retryable=True)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 200
    session = await session_manager.get_session(key)
    assert session.status.value == "active"
    assert session.consent_status is ConsentStatus.PENDING


@pytest.mark.parametrize(
    "code", ["tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"]
)
async def test_conflict_refuses_activation(session_manager, pending_session, client, studio, code):
    session_id, key = pending_session
    studio.fail(code, retryable=False)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
    )
    assert response.status_code == 409
    session = await session_manager.get_session(key)
    assert session.status.value == "pending"
    assert session.consent_status is ConsentStatus.PENDING


async def test_language_change_does_not_re_resolve_consent(
    session_manager, active_granted_session, client, studio
):
    session_id, key = active_granted_session
    studio.set_mode("ask")
    studio.reset_calls()
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "de"},
    )
    assert response.status_code == 200
    session = await session_manager.get_session(key)
    assert session.customer_language == "de"
    assert session.consent_status is ConsentStatus.GRANTED
    assert studio.calls == 0


async def test_language_change_succeeds_while_tenant_unavailable(
    session_manager, active_granted_session, client, studio
):
    session_id, key = active_granted_session
    studio.fail("tenant_suspended", retryable=False)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "de"},
    )
    assert response.status_code == 200
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.GRANTED


async def test_activation_never_routes_through_the_policy_gate(
    pending_session, client, studio, monkeypatch, session_manager
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
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.POLICY_DISABLED


@pytest.mark.parametrize("authenticated", [False, True], ids=["guest", "user"])
@pytest.mark.parametrize("selector_source", ["body", "nested_body", "query", "header", "cookie"])
async def test_activation_rejects_tenant_selectors_before_mutation(
    session_manager, pending_session, client, studio, monkeypatch, authenticated, selector_source
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
    assert (await session_manager.get_session(key)).status.value == "pending"
    assert (await session_manager.get_session(key)).customer_language is None
    assert studio.calls == 0


@pytest.mark.parametrize("actor", [None, "tenant-test", "other-tenant"])
async def test_activation_preserves_guest_and_authenticated_tenant_access(
    session_manager, pending_session, client, studio, monkeypatch, actor
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
    assert (await session_manager.get_session(key)).status.value == (
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
async def test_customer_session_routes_reject_query_tenant_selectors(
    session_manager, pending_session, client, monkeypatch, authenticated, method, suffix
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
    assert (await session_manager.get_session(key)).status.value == "pending"


class _BrokenContentStudio:
    """A v2 body with a valid policy and invalid staff and guest content."""

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url, headers, timeout_seconds):
        from services.api_gateway.studio_v1 import StudioV1HttpResponse

        self.calls += 1
        body = json.loads(_KASSEL_FIXTURE.read_text(encoding="utf-8"))
        body["tenant"]["id"] = headers["X-Studio-Tenant-Id"]
        body["staff"] = {"locale": 7}
        body["guestLanguages"][0]["feedback"] = {"questions": [{"type": "unknown"}]}
        return StudioV1HttpResponse(200, body)


async def test_invalid_content_resolves_consent_from_the_valid_policy(
    session_manager, pending_session, client, monkeypatch
):
    from services.api_gateway.studio_runtime_flow import StudioRuntimeFlow
    from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2Client

    async def token() -> str:
        return "token"

    transport = _BrokenContentStudio()
    flow = StudioRuntimeFlow(
        StudioRuntimeV2Client("https://studio.test", token, transport=transport)
    )
    monkeypatch.setitem(app.dependency_overrides, get_studio_runtime_flow, lambda: flow)
    session_id, key = pending_session

    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en", "data_retention_consent": True},
    )

    assert response.status_code == 200
    assert transport.calls == 1
    assert (await session_manager.get_session(key)).consent_status is ConsentStatus.GRANTED


def _activate(client: TestClient, session_id: str, **body) -> None:
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en", **body},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("hours", [4320, 0])
async def test_granted_consent_captures_the_reads_retention_and_revision(
    session_manager, pending_session, client, studio, hours
):
    session_id, key = pending_session
    studio.retention_hours = hours
    studio.revision = OTHER_REVISION

    _activate(client, session_id, data_retention_consent=True)

    stored = await session_manager.store.load(key)
    assert stored.consent_retention_hours == hours
    assert stored.consent_configuration_revision == OTHER_REVISION


@pytest.mark.parametrize(
    ("mode", "body", "fails"),
    [
        ("ask", {}, False),
        ("ask", {"data_retention_consent": False}, False),
        ("disabled", {"data_retention_consent": True}, False),
        ("ask", {"data_retention_consent": True}, True),
    ],
    ids=["absent", "declined", "policy-disabled", "read-failed"],
)
async def test_consent_that_is_not_granted_captures_nothing(
    session_manager, pending_session, client, studio, mode, body, fails
):
    session_id, key = pending_session
    studio.set_mode(mode)
    if fails:
        studio.fail("runtime_configuration_unavailable")

    _activate(client, session_id, **body)

    stored = await session_manager.store.load(key)
    assert stored.consent_status is not ConsentStatus.GRANTED
    assert stored.consent_retention_hours is None
    assert stored.consent_configuration_revision is None


async def test_a_retention_change_mid_session_keeps_the_captured_value(
    session_manager, active_granted_session, client, studio
):
    session_id, key = active_granted_session
    studio.retention_hours = 72
    studio.revision = OTHER_REVISION

    _activate(client, session_id, customer_language="de")
    before = datetime.now(timezone.utc)
    await session_manager.terminate_session(key, "manual_admin_termination")

    stored = await session_manager.store.load(key)
    assert stored.status.value == "terminated"
    assert stored.consent_retention_hours == 4320
    assert stored.consent_configuration_revision == REVISION
    # The terminal record expires on the captured value, not today's 72 hours.
    assert session_manager.store._expiries[key] - before >= timedelta(hours=4320)
