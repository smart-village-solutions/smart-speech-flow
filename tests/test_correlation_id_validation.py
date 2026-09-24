"""A caller-supplied correlation ID is validated once, at every entry point.

`StudioRuntimeClient` rejects a malformed correlation ID with a plain
`ValueError`. Every route that forwards the header must refuse the request with
a 400 instead of letting that surface as a 500, or -- worse on the write path --
be swallowed into a silent refusal to persist.
"""

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.session_manager import session_manager
from tests.runtime_policy_helpers import configuration

MALFORMED = ["x" * 129, "has\nnewline", "has\x00null", ""]


class _FakeStudio:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def client(self) -> "_FakeStudio":
        return self

    async def fetch(self, tenant_id: str, correlation_id: str):
        self.calls += 1
        return configuration(tenant_id=tenant_id, mode="ask")


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


def _pending(client: TestClient):
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = session_manager.resolve_customer_session(session_id)
    assert key is not None
    return session_id, key


@pytest.mark.parametrize("correlation_id", MALFORMED)
def test_activation_refuses_a_malformed_correlation_id(client, studio, correlation_id):
    session_id, key = _pending(client)
    response = client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"},
        headers={"X-Correlation-Id": correlation_id},
    )
    assert response.status_code == 400
    # The session must not have been touched by a request that was refused.
    assert session_manager.get_session(key).status.value == "pending"
    assert studio.calls == 0


def test_activation_accepts_a_well_formed_correlation_id(client, studio):
    session_id, key = _pending(client)
    response = client.post(
        "/api/customer/session/activate",
        json={
            "session_id": session_id,
            "customer_language": "en",
            "data_retention_consent": True,
        },
        headers={"X-Correlation-Id": "correlation-1"},
    )
    assert response.status_code == 200
    assert session_manager.get_session(key).consent_status is ConsentStatus.GRANTED


@pytest.mark.parametrize("correlation_id", MALFORMED)
def test_a_message_refuses_a_malformed_correlation_id(client, studio, correlation_id):
    # Not merely a 500 risk: an unvalidated header reaches the policy gate,
    # whose blanket `except Exception` turns it into a refusal to persist. That
    # would hand any client a silent switch for another guest's retention.
    session_id, _key = _pending(client)
    assert (
        client.post(
            "/api/customer/session/activate",
            json={"session_id": session_id, "customer_language": "en"},
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/customer/session/{session_id}/message",
        json={"text": "hello", "source_lang": "en", "target_lang": "de"},
        headers={"X-Correlation-Id": correlation_id},
    )
    assert response.status_code == 400
    assert "correlation" in repr(response.json()).lower()


@pytest.mark.parametrize("correlation_id", ["x" * 129, "has\nnewline"])
async def test_the_studio_client_raises_a_bare_value_error(correlation_id):
    """Why the routes must validate: this is not a classified Studio failure.

    `ValueError` is caught by neither the activation helper's Studio excepts
    nor anything that would classify it, so an unvalidated header reaches here
    and escapes as a 500 -- or is swallowed by the gate's blanket except.
    """
    from services.api_gateway.studio_runtime_client import StudioRuntimeClient

    client = StudioRuntimeClient("http://studio-mock:8000", _token)
    with pytest.raises(ValueError):
        await client.fetch("tenant-kassel", correlation_id)


async def _token() -> str:
    return "studio-mock-authorized-token"
