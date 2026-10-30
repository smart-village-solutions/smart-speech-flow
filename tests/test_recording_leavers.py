"""Leavers: the directory guards, the service's refusals and the routes (spec §9.8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.leavers import KeyHolder, LeaverError, Leavers, MarkedLeaver
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.routes.recording_leavers import get_leavers
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.test_recording_ceremony_routes import CUSTODIAN, MANAGE, TENANT, Caller

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
BASE = "/api/admin/recording/leavers"


def _holder(sub: str, *, custodian: bool = False) -> KeyHolder:
    return KeyHolder(sub, 1, b"\x01" * 32, NOW, 3, NOW, custodian, "Carol" if custodian else None)


@dataclass
class FakeLeaverStore:
    holders_: list[KeyHolder] = field(
        default_factory=lambda: [_holder("alice"), _holder("bob"), _holder("carol", custodian=True)]
    )
    refusal: str | None = None
    failing: bool = False
    marked: list[tuple[str, int, str]] = field(default_factory=list)

    async def holders(self, tenant_id: str) -> list[KeyHolder]:
        if self.failing:
            raise RecordingStorageUnavailable("down")
        return self.holders_

    async def mark(self, tenant_id, sub, key_version, actor, now):
        if self.refusal is not None:
            return Refused(self.refusal)
        self.marked.append((sub, key_version, actor))
        return MarkedLeaver(sub, key_version, sub == "carol", 2)


@dataclass
class FakeMembers:
    """None stands for Studio being unreachable."""

    subs: frozenset[str] | None = frozenset({"bob", "dieter"})

    async def members(self, tenant_id: str, correlation_id: str) -> frozenset[str] | None:
        return self.subs


def _service(store=None, members=None) -> tuple[Leavers, FakeLeaverStore, FakeMembers]:
    store = store or FakeLeaverStore()
    members = members or FakeMembers()
    return Leavers(store=store, directory=members, clock=lambda: NOW), store, members


async def test_candidates_are_key_holders_missing_from_the_directory():
    service, _, _ = _service()
    assert [h.sub for h in await service.candidates(TENANT, "c")] == ["alice", "carol"]


@pytest.mark.parametrize("subs", [None, frozenset(), frozenset({"dieter"})])
async def test_a_failed_or_implausible_directory_lists_nobody(subs):
    service, _, _ = _service(members=FakeMembers(subs))
    with pytest.raises(LeaverError) as raised:
        await service.candidates(TENANT, "c")
    assert raised.value.code == "directory_unavailable"


async def test_a_tenant_without_keys_lists_nobody_even_from_an_empty_directory():
    service, _, _ = _service(FakeLeaverStore(holders_=[]), FakeMembers(frozenset()))
    assert await service.candidates(TENANT, "c") == []


async def test_marking_someone_still_in_the_directory_never_reaches_the_store():
    service, store, _ = _service()
    with pytest.raises(LeaverError) as raised:
        await service.mark(TENANT, "admin", "bob", 1, "c")
    assert raised.value.code == "still_in_directory" and store.marked == []


@pytest.mark.parametrize("subs", [None, frozenset(), frozenset({"dieter"})])
async def test_marking_refuses_a_failed_or_implausible_directory(subs):
    service, store, _ = _service(members=FakeMembers(subs))
    with pytest.raises(LeaverError) as raised:
        await service.mark(TENANT, "admin", "alice", 1, "c")
    assert raised.value.code == "directory_unavailable" and store.marked == []


async def test_marking_passes_the_admin_and_version_and_maps_refusals():
    service, store, _ = _service()
    assert await service.mark(TENANT, "admin", "alice", 1, "c") == MarkedLeaver(
        "alice", 1, False, 2
    )
    assert store.marked == [("alice", 1, "admin")]
    store.refusal = "key_changed"
    with pytest.raises(LeaverError) as raised:
        await service.mark(TENANT, "admin", "alice", 1, "c")
    assert raised.value.code == "key_changed"


async def test_storage_failure_is_unavailable():
    service, _, _ = _service(FakeLeaverStore(failing=True))
    with pytest.raises(LeaverError) as raised:
        await service.candidates(TENANT, "c")
    assert raised.value.code == "unavailable"


@pytest.fixture
def http():
    service, store, members = _service()
    caller = Caller()
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    app.dependency_overrides[get_leavers] = lambda: service
    yield TestClient(app), caller, store, members
    for dependency in (get_leavers, require_ssf_user):
        app.dependency_overrides.pop(dependency, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def test_the_list_over_http(http):
    client, caller, _, _ = http
    caller.be("admin", MANAGE, fresh=False)
    response = client.get(BASE)
    assert response.status_code == 200
    carol = response.json()["candidates"][1]
    assert carol["sub"] == "carol" and carol["custodian"] is True
    assert (carol["display_name"], carol["conversations"]) == ("Carol", 3)
    assert carol["fingerprint_display"] and carol["enrolled_at"] == NOW.isoformat()


def test_marking_over_http_needs_the_admin_and_step_up(http):
    client, caller, store, _ = http
    caller.be("admin", CUSTODIAN)
    assert _code(client.post(f"{BASE}/alice", json={"key_version": 1})) == "PERMISSION_REQUIRED"
    assert _code(client.get(BASE)) == "PERMISSION_REQUIRED"
    caller.be("admin", MANAGE, fresh=False)
    assert _code(client.post(f"{BASE}/alice", json={"key_version": 1})) == "STEP_UP_REQUIRED"
    caller.be("admin", MANAGE)
    response = client.post(f"{BASE}/alice", json={"key_version": 1})
    assert response.status_code == 200
    assert response.json() == {
        "sub": "alice",
        "key_version": 1,
        "custodian": False,
        "wraps_deleted": 2,
    }
    assert store.marked == [("alice", 1, "admin")]


@pytest.mark.parametrize(
    ("refusal", "status", "code"),
    [
        ("already_left", 409, "ALREADY_LEFT"),
        ("key_not_enrolled", 404, "KEY_NOT_ENROLLED"),
        ("key_changed", 409, "KEY_CHANGED"),
        ("ceremony_in_progress", 409, "CEREMONY_IN_PROGRESS"),
    ],
)
def test_each_store_refusal_has_its_answer(http, refusal, status, code):
    client, caller, store, _ = http
    caller.be("admin", MANAGE)
    store.refusal = refusal
    response = client.post(f"{BASE}/alice", json={"key_version": 1})
    assert (response.status_code, _code(response)) == (status, code)


def test_the_directory_answers_over_http(http):
    client, caller, _, members = http
    caller.be("admin", MANAGE)
    assert _code(client.post(f"{BASE}/bob", json={"key_version": 1})) == "STILL_IN_DIRECTORY"
    members.subs = None
    response = client.get(BASE)
    assert (response.status_code, _code(response)) == (503, "DIRECTORY_UNAVAILABLE")


def test_a_malformed_sub_or_body_is_refused_before_the_service(http):
    client, caller, store, _ = http
    caller.be("admin", MANAGE)
    assert client.post(f"{BASE}/-bad", json={"key_version": 1}).status_code == 422
    assert client.post(f"{BASE}/alice", json={"key_version": 0}).status_code == 422
    assert client.post(f"{BASE}/alice", json={"key_version": 1, "x": 1}).status_code == 422
    assert store.marked == []


def test_without_recording_the_routes_answer_503():
    caller = Caller()
    caller.be("admin", MANAGE)
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    try:
        response = TestClient(app).get(BASE)
    finally:
        app.dependency_overrides.pop(require_ssf_user, None)
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")


def test_marking_over_http_answers_503_for_a_failed_directory_or_store(http):
    client, caller, store, members = http
    caller.be("admin", MANAGE)
    members.subs = None
    response = client.post(f"{BASE}/alice", json={"key_version": 1})
    assert (response.status_code, _code(response)) == (503, "DIRECTORY_UNAVAILABLE")
    members.subs = frozenset({"bob"})
    store.failing = True
    response = client.post(f"{BASE}/alice", json={"key_version": 1})
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")
    assert store.marked == []
