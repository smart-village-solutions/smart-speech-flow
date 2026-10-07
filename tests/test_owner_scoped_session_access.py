"""A session is the admin's who created it; colleagues get the unknown-session 404 (#476)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.session_models import SessionStatus
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    admin_ref,
    require_studio_tenant_context,
)
from services.api_gateway.tenant_session import TenantSessionKey
from tests.gateway_contract.contract_support import runtime_read

TENANT = "tenant-a"
REVISION = f"sha256:{'a' * 64}"
NOT_FOUND = {"detail": "Session not found"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    original_overrides = app.dependency_overrides.copy()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


def _as(subject: str) -> None:
    context = StudioTenantContext(TENANT, REVISION)
    configuration = runtime_read(TENANT)
    app.dependency_overrides[require_ssf_user] = lambda: {"sub": subject}
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, configuration, "test-correlation")
    )


def _create(client: TestClient, subject: str) -> str:
    _as(subject)
    response = client.post("/api/admin/session/create")
    assert response.status_code == 201
    return response.json()["session_id"]


async def _status(session_id: str) -> SessionStatus:
    session = await app.state.dependencies.session_manager.get_session(
        TenantSessionKey(TENANT, session_id)
    )
    assert session is not None
    return session.status


def _ticket(client: TestClient, session_id: str, transport: str) -> str:
    response = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket", json={"transport": transport}
    )
    assert response.status_code == 200
    return response.json()["ticket"]


def _polling_id(client: TestClient, session_id: str) -> str:
    ticket = _ticket(client, session_id, "polling")
    response = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )
    assert response.status_code == 200
    return response.json()["polling_id"]


def _session_routes(session_id: str) -> list[tuple[str, str, dict[str, object] | None]]:
    base = f"/api/admin/session/{session_id}"
    return [
        ("GET", f"{base}/status", None),
        ("GET", f"{base}/messages", None),
        ("GET", f"{base}/audio/message-1/translated.wav", None),
        ("POST", f"{base}/message", {}),
        ("POST", f"{base}/realtime-ticket", {"transport": "websocket"}),
        ("POST", f"{base}/realtime-ticket", {"transport": "polling"}),
        ("GET", f"{base}/realtime/connections", None),
        ("GET", f"/api/admin/session/current?session_id={session_id}", None),
        ("DELETE", f"{base}/terminate", None),
    ]


def _call(client: TestClient, method: str, path: str, body: dict[str, object] | None):
    return client.request(method, path, json=body)


async def test_a_colleague_gets_the_unknown_session_404_on_every_session_route(client):
    alice = _create(client, "alice-subject")
    _create(client, "bob-subject")

    for method, path, body in _session_routes(alice):
        response = _call(client, method, path, body)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), (method, path)

    assert await _status(alice) is SessionStatus.PENDING


async def test_the_owner_is_served_on_every_session_route(client):
    alice = _create(client, "alice-subject")
    _create(client, "bob-subject")
    _as("alice-subject")

    # Past the access check: the unknown message's audio is "Audio file not found",
    # and a message into a still-pending session is refused as not active.
    expected = [200, 200, 404, 400, 200, 200, 200, 200, 200]
    for (method, path, body), code in zip(_session_routes(alice), expected, strict=True):
        response = _call(client, method, path, body)
        assert response.status_code == code, (method, path, response.text)
        assert response.json() != NOT_FOUND, (method, path)

    assert await _status(alice) is SessionStatus.TERMINATED


def test_a_colleague_cannot_use_the_owners_polling_channel(client):
    alice = _create(client, "alice-subject")
    polling_id = _polling_id(client, alice)
    base = f"/api/admin/session/{alice}/polling/{polling_id}"
    _create(client, "bob-subject")

    for method, path, body in [
        ("GET", f"{base}?timeout=0", None),
        ("POST", f"{base}/send", {"type": "heartbeat", "content": {}}),
        ("GET", f"{base}/status", None),
        ("POST", f"{base}/recover", None),
        ("DELETE", base, None),
    ]:
        response = _call(client, method, path, body)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), (method, path)

    _as("alice-subject")
    assert client.get(f"{base}/status").status_code == 200


def test_a_colleague_cannot_spend_the_owners_polling_ticket(client):
    alice = _create(client, "alice-subject")
    _as("alice-subject")
    ticket = _ticket(client, alice, "polling")
    _create(client, "bob-subject")
    activate = f"/api/admin/session/{alice}/polling/activate"

    response = client.post(activate, json={"ticket": ticket})

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    _as("alice-subject")
    assert client.post(activate, json={"ticket": ticket}).status_code == 200


def test_a_colleagues_ended_session_stays_hidden(client):
    alice = _create(client, "alice-subject")
    _as("alice-subject")
    assert client.delete(f"/api/admin/session/{alice}/terminate").status_code == 200
    _create(client, "bob-subject")

    for suffix in ("status", "messages"):
        response = client.get(f"/api/admin/session/{alice}/{suffix}")
        assert (response.status_code, response.json()) == (404, NOT_FOUND), suffix

    _as("alice-subject")
    assert client.get(f"/api/admin/session/{alice}/status").status_code == 200


async def _owner_less_session() -> str:
    manager = app.state.dependencies.session_manager
    session = await manager.create_admin_session(TENANT, REVISION)
    return session.id


async def test_a_session_without_an_owner_is_denied_to_every_admin(client):
    legacy = client.portal.call(_owner_less_session)
    _create(client, "alice-subject")

    for method, path, body in _session_routes(legacy):
        response = _call(client, method, path, body)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), (method, path)

    assert await _status(legacy) is SessionStatus.PENDING
    history = client.get("/api/admin/session/history").json()
    listed = {row["id"] for row in history["sessions"] + history["active_sessions"]}
    assert legacy not in listed


def test_each_admins_history_holds_only_their_own_sessions(client):
    alice_ended = _create(client, "alice-subject")
    alice_live = _create(client, "alice-subject")
    bob_ended = _create(client, "bob-subject")
    bob_live = _create(client, "bob-subject")

    for subject, ended, live in (
        ("alice-subject", alice_ended, alice_live),
        ("bob-subject", bob_ended, bob_live),
    ):
        _as(subject)
        body = client.get("/api/admin/session/history").json()
        assert [row["id"] for row in body["sessions"]] == [ended]
        assert [row["id"] for row in body["active_sessions"]] == [live]
        assert body["total_count"] == 1


def test_the_history_limit_counts_only_the_admins_own_sessions(client):
    alice_ended = _create(client, "alice-subject")
    _create(client, "alice-subject")
    for _ in range(3):
        bob = _create(client, "bob-subject")
        client.delete(f"/api/admin/session/{bob}/terminate")

    _as("alice-subject")
    body = client.get("/api/admin/session/history", params={"limit": 1}).json()

    assert [row["id"] for row in body["sessions"]] == [alice_ended]


def test_the_tenant_connection_listing_omits_colleagues_sessions(client):
    alice = _create(client, "alice-subject")
    _polling_id(client, alice)
    bob = _create(client, "bob-subject")
    _polling_id(client, bob)

    for subject, own in (("alice-subject", alice), ("bob-subject", bob)):
        _as(subject)
        body = client.get("/api/admin/realtime/connections").json()
        assert {row["session_id"] for row in body["connections"]} == {own}
        assert body["count"] == 1


def test_a_denial_logs_a_fixed_outcome_and_no_owner(client, caplog):
    alice = _create(client, "alice-subject")
    _create(client, "bob-subject")

    with caplog.at_level(logging.INFO):
        client.get(f"/api/admin/session/{alice}/status")

    denials = [
        r for r in caplog.records if r.getMessage().startswith("tenant_session_access_denied")
    ]
    assert [getattr(r, "outcome", None) for r in denials] == ["owner_mismatch"]
    for subject in ("alice-subject", "bob-subject"):
        assert admin_ref(TENANT, subject) not in caplog.text
        assert subject not in caplog.text
