"""The supervisor's retention routes: permission, step-up, bounds and coded errors (§16.1)."""

from __future__ import annotations

import dataclasses
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.retention.decisions import (
    MAX_EXTENSION,
    ConversationSummary,
    RetentionDecision,
)
from services.api_gateway.routes.recording_retention import get_retention_decisions
from services.api_gateway.tenant_context import require_studio_tenant_context

TENANT = "tenant-test"
BASE = "/api/admin/recording/conversations"


class FakeDecisions:
    def __init__(self, *summaries: ConversationSummary) -> None:
        self.rows = {summary.conversation_id: summary for summary in summaries}
        self.decided: list[tuple[RetentionDecision, str]] = []
        self.not_found: list[tuple[str, str, str]] = []
        self.cursors: list[tuple] = []

    async def summary(self, tenant_id, conversation_id):
        return self.rows.get(conversation_id) if tenant_id == TENANT else None

    async def summaries(self, tenant_id, *, limit, started_before, before_id=None):
        self.cursors.append((started_before, before_id))
        rows = sorted(self.rows.values(), key=lambda row: row.started_at, reverse=True)
        return [row for row in rows if started_before is None or row.started_at < started_before][
            :limit
        ]

    async def decide(self, decision, event_type):
        self.decided.append((decision, event_type))
        row = self.rows[decision.conversation_id]
        if decision.kind == "extend":
            row = dataclasses.replace(row, retention_until=decision.retain_until)
        else:
            row = dataclasses.replace(row, legal_hold=decision.kind == "hold_on")
        self.rows[decision.conversation_id] = row
        return row

    async def record_not_found(self, tenant_id, actor_sub, conversation_ref, at):
        self.not_found.append((tenant_id, actor_sub, conversation_ref))


def _summary(*, retention_until=None, legal_hold=False, started_at=None) -> ConversationSummary:
    now = datetime.now(timezone.utc)
    return ConversationSummary(
        conversation_id=str(uuid.uuid4()),
        employee_sub="emp",
        started_at=started_at or now - timedelta(days=1),
        ended_at=now - timedelta(hours=23),
        retention_until=retention_until or now + timedelta(days=30),
        legal_hold=legal_hold,
        shredded_at=None,
    )


def _claims(*, permissions=("ssf.recording.supervise",), fresh=True) -> dict:
    claims = {"sub": "sup", "_ssf_verified_tenant_id": TENANT, "ssf_permissions": list(permissions)}
    if fresh:
        claims |= {"acr": "mfa", "auth_time": int(time.time()) - 5}
    return claims


@pytest.fixture
def client_for():
    def build(claims: dict, decisions: FakeDecisions | None) -> TestClient:
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        if decisions is not None:
            app.dependency_overrides[get_retention_decisions] = lambda: decisions
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_retention_decisions, None)
    app.dependency_overrides.pop(require_ssf_user, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _calls(conversation_id: str) -> list[tuple[str, str, dict | None]]:
    until = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    return [
        ("GET", BASE, None),
        ("GET", f"{BASE}/{conversation_id}", None),
        ("POST", f"{BASE}/{conversation_id}/retention", {"until": until, "reason": "court"}),
        ("POST", f"{BASE}/{conversation_id}/legal-hold", {"on": True, "reason": "court"}),
    ]


def test_every_route_needs_the_supervise_permission(client_for):
    row = _summary()
    decisions = FakeDecisions(row)
    client = client_for(_claims(permissions=("ssf.recording.review",)), decisions)
    for method, path, body in _calls(row.conversation_id):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, path
        assert _code(response) == "PERMISSION_REQUIRED"
    assert decisions.decided == []


def test_changes_need_a_fresh_mfa_login(client_for):
    row = _summary()
    decisions = FakeDecisions(row)
    client = client_for(_claims(fresh=False), decisions)
    for method, path, body in _calls(row.conversation_id)[2:]:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, path
        assert _code(response) == "STEP_UP_REQUIRED"
    assert decisions.decided == []
    assert client.get(f"{BASE}/{row.conversation_id}").status_code == 200


def test_an_extension_is_decided_by_the_caller_and_returns_the_new_date(client_for):
    row = _summary()
    decisions = FakeDecisions(row)
    until = row.retention_until + timedelta(days=1)
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/retention",
        json={"until": until.isoformat(), "reason": "court order"},
    )
    assert response.status_code == 200
    assert response.json()["retention_until"] == until.isoformat()
    [(decision, event_type)] = decisions.decided
    assert (decision.kind, decision.actor_sub, decision.reason, decision.retain_until) == (
        "extend",
        "sup",
        "court order",
        until,
    )
    assert (decision.tenant_id, decision.conversation_id) == (TENANT, row.conversation_id)
    assert event_type == "recording.retention.extended"


@pytest.mark.parametrize(
    ("offset", "status", "code"),
    [
        ("same", 409, "RETENTION_NOT_EXTENDED"),
        ("earlier", 409, "RETENTION_NOT_EXTENDED"),
        ("too_far", 422, "RETENTION_TOO_FAR"),
    ],
)
def test_an_extension_out_of_bounds_is_refused_before_any_decision(
    client_for, offset, status, code
):
    row = _summary()
    decisions = FakeDecisions(row)
    until = {
        "same": row.retention_until,
        "earlier": row.retention_until - timedelta(seconds=1),
        "too_far": datetime.now(timezone.utc) + MAX_EXTENSION + timedelta(minutes=1),
    }[offset]
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/retention",
        json={"until": until.isoformat(), "reason": "court"},
    )
    assert response.status_code == status
    assert _code(response) == code
    assert decisions.decided == []


def test_an_unknown_conversation_is_a_404_and_audited(client_for):
    decisions = FakeDecisions(_summary())
    client = client_for(_claims(), decisions)
    missing = str(uuid.uuid4())
    for method, path, body in _calls(missing)[1:]:
        response = client.request(method, path, json=body)
        assert response.status_code == 404, path
        assert _code(response) == "CONVERSATION_NOT_FOUND"
    assert decisions.not_found == [(TENANT, "sup", missing)] * 3
    assert decisions.decided == []


def test_a_malformed_conversation_id_is_a_422(client_for):
    response = client_for(_claims(), FakeDecisions()).get(f"{BASE}/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.parametrize(("days", "expires_now"), [(-1, True), (1, False)])
def test_lifting_a_hold_says_whether_the_conversation_expires_now(client_for, days, expires_now):
    row = _summary(
        retention_until=datetime.now(timezone.utc) + timedelta(days=days), legal_hold=True
    )
    decisions = FakeDecisions(row)
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/legal-hold", json={"on": False, "reason": "case closed"}
    )
    assert response.status_code == 200
    assert response.json()["legal_hold"] is False
    assert response.json()["expires_now"] is expires_now
    [(decision, event_type)] = decisions.decided
    assert (decision.kind, decision.retain_until, event_type) == (
        "hold_off",
        None,
        "recording.legal_hold.off",
    )


@pytest.mark.parametrize(
    ("ended", "started_hours_ago"), [(None, 2), (timedelta(hours=-1), 30), (None, 30)]
)
def test_lifting_a_hold_expires_now_only_for_an_ended_or_long_started_conversation(
    client_for, ended, started_hours_ago
):
    now = datetime.now(timezone.utc)
    row = dataclasses.replace(
        _summary(retention_until=now - timedelta(days=1), legal_hold=True),
        started_at=now - timedelta(hours=started_hours_ago),
        ended_at=None if ended is None else now + ended,
    )
    response = client_for(_claims(), FakeDecisions(row)).post(
        f"{BASE}/{row.conversation_id}/legal-hold", json={"on": False, "reason": "closed"}
    )
    assert response.json()["expires_now"] is (ended is not None or started_hours_ago > 24)


def test_setting_a_hold_never_expires_now(client_for):
    row = _summary(retention_until=datetime.now(timezone.utc) - timedelta(days=1))
    decisions = FakeDecisions(row)
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/legal-hold", json={"on": True, "reason": "court"}
    )
    assert response.json()["expires_now"] is False
    assert decisions.decided[0][1] == "recording.legal_hold.on"


@pytest.mark.parametrize(
    "body",
    [
        {"on": True, "reason": ""},
        {"on": True, "reason": "x" * 501},
        {"on": True},
        {"on": True, "reason": "court", "until": "2030-01-01T00:00:00+00:00"},
    ],
)
def test_a_hold_needs_a_reason_of_at_most_500_characters(client_for, body):
    row = _summary()
    decisions = FakeDecisions(row)
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/legal-hold", json=body
    )
    assert response.status_code == 422
    assert decisions.decided == []


def test_an_extension_date_needs_a_time_zone(client_for):
    row = _summary()
    decisions = FakeDecisions(row)
    response = client_for(_claims(), decisions).post(
        f"{BASE}/{row.conversation_id}/retention",
        json={"until": "2030-01-01T00:00:00", "reason": "court"},
    )
    assert response.status_code == 422
    assert decisions.decided == []


def test_the_list_is_newest_first_and_pages_by_start(client_for):
    now = datetime.now(timezone.utc)
    older, newer = _summary(started_at=now - timedelta(days=2)), _summary(started_at=now)
    client = client_for(_claims(), FakeDecisions(older, newer))
    first = client.get(BASE, params={"limit": 1})
    assert [row["conversation_id"] for row in first.json()["conversations"]] == [
        newer.conversation_id
    ]
    rest = client.get(BASE, params={"started_before": newer.started_at.isoformat()})
    assert [row["conversation_id"] for row in rest.json()["conversations"]] == [
        older.conversation_id
    ]
    for limit in (0, 101):
        assert client.get(BASE, params={"limit": limit}).status_code == 422


def test_the_next_page_is_asked_for_by_start_and_id(client_for):
    decisions = FakeDecisions(_summary())
    client = client_for(_claims(), decisions)
    boundary, last = "2026-10-28T12:00:00+00:00", "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
    response = client.get(BASE, params={"started_before": boundary, "before_id": last})
    assert response.status_code == 200
    assert decisions.cursors[-1] == (datetime.fromisoformat(boundary), last)
    assert client.get(BASE, params={"before_id": "not-a-uuid"}).status_code == 422


def test_an_unwired_gateway_answers_503(client_for):
    response = client_for(_claims(), None).get(BASE)
    assert response.status_code == 503
    assert _code(response) == "RECORDING_UNAVAILABLE"
