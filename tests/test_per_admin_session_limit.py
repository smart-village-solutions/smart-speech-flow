"""One live conversation per admin, not per tenant (#473)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.session_lifecycle import NoActiveSessionError, SessionLifecycleService
from services.api_gateway.session_manager import Session, SessionStatus, TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    admin_ref,
    require_studio_tenant_context,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from tests.gateway_contract.contract_support import runtime_configuration

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
ALICE = admin_ref("tenant-a", "alice-subject")
BOB = admin_ref("tenant-a", "bob-subject")


def _manager(store: MemoryTenantSessionStore | None = None) -> TenantSessionManager:
    return TenantSessionManager(
        store=store or MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )


def _status(manager: TenantSessionManager, session: Session) -> SessionStatus:
    stored = manager.get_session(session.key)
    assert stored is not None
    return stored.status


def test_admin_ref_is_a_stable_hash_scoped_to_the_tenant():
    assert admin_ref("tenant-a", "alice-subject") == ALICE
    assert len(ALICE) == 32
    assert "alice" not in ALICE
    assert ALICE != BOB
    assert admin_ref("tenant-b", "alice-subject") != ALICE


async def test_two_admins_of_one_tenant_converse_in_parallel():
    manager = _manager()

    alice = await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=ALICE)
    bob = await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=BOB)

    assert _status(manager, alice) is SessionStatus.PENDING
    assert _status(manager, bob) is SessionStatus.PENDING


async def test_an_admins_new_conversation_ends_only_their_own_previous_one():
    manager = _manager()
    first = await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=ALICE)
    colleague = await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=BOB)

    second = await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=ALICE)

    ended = manager.get_session(first.key)
    assert ended is not None
    assert ended.status is SessionStatus.TERMINATED
    assert ended.termination_reason == "new_session_created"
    assert _status(manager, colleague) is SessionStatus.PENDING
    assert _status(manager, second) is SessionStatus.PENDING


async def test_an_owner_less_legacy_session_is_not_ended_by_an_admin():
    manager = _manager()
    legacy = await manager.create_admin_session("tenant-a", SNAPSHOT)

    await manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref=ALICE)

    assert _status(manager, legacy) is SessionStatus.PENDING


async def test_a_create_without_an_owner_ends_nothing():
    manager = _manager()
    legacy = await manager.create_admin_session("tenant-a", SNAPSHOT)

    await manager.create_admin_session("tenant-a", SNAPSHOT)

    assert _status(manager, legacy) is SessionStatus.PENDING


async def test_the_rule_holds_across_a_gateway_restart():
    store = MemoryTenantSessionStore()
    before_restart = await _manager(store).create_admin_session(
        "tenant-a", SNAPSHOT, owner_ref=ALICE
    )

    restarted = _manager(store)
    await restarted.create_admin_session("tenant-a", SNAPSHOT, owner_ref=ALICE)

    assert _status(restarted, before_restart) is SessionStatus.TERMINATED


def test_the_owner_survives_the_stored_representation():
    session = Session(id="ABCDEFGH", tenant_id="tenant-a", runtime_configuration=SNAPSHOT)
    session.owner_ref = ALICE

    stored = json.loads(json.dumps(session.to_dict(include_messages=True)))

    assert Session.from_dict(stored).owner_ref == ALICE


def test_the_owner_never_reaches_public_output():
    session = Session(id="ABCDEFGH", tenant_id="tenant-a", runtime_configuration=SNAPSHOT)
    session.owner_ref = ALICE

    assert "owner_ref" not in session.to_public_dict()


async def test_current_is_the_requesting_admins_own_conversation():
    manager = _manager()
    lifecycle = SessionLifecycleService(manager)
    alice = await lifecycle.create("tenant-a", runtime_configuration("tenant-a"), owner_ref=ALICE)
    bob = await lifecycle.create("tenant-a", runtime_configuration("tenant-a"), owner_ref=BOB)

    assert lifecycle.current("tenant-a", None, owner_ref=ALICE).id == alice.id
    assert lifecycle.current("tenant-a", None, owner_ref=BOB).id == bob.id
    with pytest.raises(NoActiveSessionError):
        lifecycle.current("tenant-a", None, owner_ref=admin_ref("tenant-a", "carol-subject"))


async def test_a_named_session_is_still_found_for_any_admin_of_the_tenant():
    manager = _manager()
    lifecycle = SessionLifecycleService(manager)
    alice = await lifecycle.create("tenant-a", runtime_configuration("tenant-a"), owner_ref=ALICE)

    assert lifecycle.current("tenant-a", alice.id, owner_ref=BOB).id == alice.id


@pytest.fixture
def http_client():
    original_overrides = app.dependency_overrides.copy()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


def _authenticate_as(subject: str) -> None:
    context = StudioTenantContext("tenant-a", REVISION)
    configuration = runtime_configuration("tenant-a")
    app.dependency_overrides[require_ssf_user] = lambda: {"sub": subject}
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, configuration, "test-correlation")
    )


def test_http_admins_each_keep_their_own_conversation(http_client: TestClient) -> None:
    manager = app.state.dependencies.session_manager
    _authenticate_as("alice-subject")
    alice = http_client.post("/api/admin/session/create").json()["session_id"]
    _authenticate_as("bob-subject")
    bob = http_client.post("/api/admin/session/create").json()["session_id"]

    for session_id in (alice, bob):
        stored = manager.get_session(TenantSessionKey("tenant-a", session_id))
        assert stored is not None
        assert stored.status is SessionStatus.PENDING
    assert http_client.get("/api/admin/session/current").json()["session_id"] == bob
    _authenticate_as("alice-subject")
    assert http_client.get("/api/admin/session/current").json()["session_id"] == alice


def test_http_history_never_carries_the_owner(http_client: TestClient) -> None:
    _authenticate_as("alice-subject")
    http_client.post("/api/admin/session/create")
    http_client.post("/api/admin/session/create")

    response = http_client.get("/api/admin/session/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body["sessions"]) == 1
    assert len(body["active_sessions"]) == 1
    assert "owner_ref" not in response.text
    assert admin_ref("tenant-a", "alice-subject") not in response.text
