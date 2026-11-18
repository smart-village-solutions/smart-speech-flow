"""Dashboard composition keeps ownership and encrypted metadata boundaries."""

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.dashboard import Dashboard, DashboardCursor, DashboardUnavailableError
from services.api_gateway.session_models import Session, SessionStatus
from services.api_gateway.session_pseudonym import SessionPseudonymizer

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


class Sessions:
    def __init__(self, rows):
        self.rows = rows

    async def list_for_tenant(self, tenant_id):
        return [row for row in self.rows if row.tenant_id == tenant_id]


class Recordings:
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail = list(rows), fail

    async def overview(self, tenant_id, sub, refs, before, limit, supervisor):
        if self.fail:
            raise DashboardUnavailableError
        return self.rows


def session(sid="OWN", **kwargs):
    return Session(id=sid, tenant_id="tenant-a", owner_ref="owner", created_at=NOW, **kwargs)


def dashboard(rows, recordings=None):
    pseudonymizer = SessionPseudonymizer(key=b"test-key")
    service = Dashboard(Sessions(rows), recordings, pseudonymizer, DashboardCursor(bytes(32)))
    return service, pseudonymizer


async def test_only_own_retained_sessions_and_no_content():
    other = session("OTHER")
    other.owner_ref = "colleague"
    owned = session(customer_language="en")
    owned.messages = [object()]
    service, _ = dashboard([owned, other])
    result = await service.conversations("tenant-a", "alice", "owner", frozenset(), 50, None)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["session_id"] == "OWN"
    assert item["customer_language"] == "en"
    assert item["actions"] == ["resume"]
    assert "owner" not in repr(result)
    assert "messages" not in item


async def test_joined_recording_hides_language_and_deduplicates():
    service, pseudo = dashboard([session(customer_language="en")])
    service.recordings = Recordings(
        [
            {
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "session_ref": pseudo.recording_reference("OWN"),
                "employee_sub": "alice",
                "started_at": NOW,
                "ended_at": None,
                "incomplete": False,
                "can_open": False,
                "verification_statuses": [],
            }
        ]
    )
    result = await service.conversations(
        "tenant-a", "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
    )
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["session_id"] == "OWN"
    assert item["recording_id"] is None
    assert item["customer_language"] is None
    assert item["language_visibility"] == "encrypted"
    assert pseudo.recording_reference("OWN") not in repr(result)


async def test_archive_only_row_survives_session_expiry():
    row = {
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "session_ref": "hidden",
        "employee_sub": "someone",
        "started_at": NOW,
        "ended_at": NOW,
        "incomplete": True,
        "can_open": True,
        "verification_statuses": ["approved"],
    }
    service, _ = dashboard([], Recordings([row]))
    result = await service.conversations(
        "tenant-a", "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
    )
    assert result["items"][0]["origin"] == "transferred"
    assert result["items"][0]["session_id"] is None
    assert result["items"][0]["verification"]["approved"] == 1


async def test_required_archive_source_failure_does_not_claim_unrecorded():
    service, _ = dashboard([session()], Recordings(fail=True))
    with pytest.raises(DashboardUnavailableError):
        await service.conversations(
            "tenant-a", "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
        )


async def test_cursor_pages_are_identity_bound_and_tamper_resistant():
    first = session("NEW")
    older = session("OLD", status=SessionStatus.TERMINATED)
    older.created_at = NOW - timedelta(days=1)
    service, _ = dashboard([first, older])
    page1 = await service.conversations("tenant-a", "alice", "owner", frozenset(), 1, None)
    cursor = page1["next_cursor"]
    assert cursor
    page2 = await service.conversations("tenant-a", "alice", "owner", frozenset(), 1, cursor)
    assert [item["session_id"] for item in page2["items"]] == ["OLD"]
    with pytest.raises(ValueError):
        await service.conversations("tenant-a", "bob", "owner", frozenset(), 1, cursor)
    with pytest.raises(ValueError):
        await service.conversations(
            "tenant-a", "alice", "owner", frozenset(), 1, cursor[:-2] + "!!"
        )


async def test_unavailable_recording_is_not_presented_as_unrecorded_details():
    closed = session(status=SessionStatus.TERMINATED)
    service, pseudo = dashboard([closed])
    pseudo.mark_recorded("OWN")
    result = await service.conversations("tenant-a", "alice", "owner", frozenset(), 50, None)
    row = result["items"][0]
    assert row["recording_status"] == "unavailable"
    assert row["actions"] == []


async def test_session_store_failure_reports_unavailable():
    from redis.exceptions import RedisError

    class UnavailableSessions:
        async def list_for_tenant(self, tenant):
            raise RedisError("private backend connection detail")

    service, _ = dashboard([])
    service.sessions = UnavailableSessions()
    with pytest.raises(DashboardUnavailableError):
        await service.conversations("tenant-a", "alice", "owner", frozenset(), 50, None)


async def test_losing_recording_permission_does_not_expose_recorded_language():
    service, pseudo = dashboard([session(customer_language="en")])
    service.recordings = Recordings(
        [
            {
                "conversation_id": "00000000-0000-0000-0000-000000000003",
                "session_ref": pseudo.recording_reference("OWN"),
                "employee_sub": "alice",
                "started_at": NOW,
                "ended_at": None,
                "incomplete": False,
                "can_open": True,
                "verification_statuses": [],
            }
        ]
    )
    result = await service.conversations("tenant-a", "alice", "owner", frozenset(), 50, None)
    assert result["items"][0]["customer_language"] is None
    assert "open_recording" not in result["items"][0]["actions"]


async def test_inaccessible_archive_only_metadata_is_not_listed():
    row = {
        "conversation_id": "00000000-0000-0000-0000-000000000004",
        "session_ref": "expired-session",
        "employee_sub": "alice",
        "started_at": NOW,
        "ended_at": NOW,
        "incomplete": False,
        "can_open": False,
        "verification_statuses": ["approved"],
    }
    service, _ = dashboard([], Recordings([row]))
    page = await service.conversations(
        "tenant-a", "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
    )
    assert page["items"] == []


def test_cursor_and_session_reference_are_stable_across_instances(monkeypatch):
    import base64

    monkeypatch.delenv("SSF_QUALITY_TELEMETRY_SESSION_KEY", raising=False)
    monkeypatch.setenv("SSF_FEEDBACK_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    first, second = DashboardCursor.from_environment(), DashboardCursor.from_environment()
    token = first.encode("t", "u", (NOW.isoformat(), "row"))
    assert second.decode("t", "u", token) == (NOW.isoformat(), "row")
    assert first.row_id("t", "session") == second.row_id("t", "session")
    assert SessionPseudonymizer.from_environment().recording_reference(
        "session"
    ) == SessionPseudonymizer.from_environment().recording_reference("session")


def test_cursor_configuration_never_silently_falls_back_to_process_random(monkeypatch):
    monkeypatch.delenv("SSF_QUALITY_TELEMETRY_SESSION_KEY", raising=False)
    monkeypatch.delenv("SSF_FEEDBACK_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValueError):
        DashboardCursor.from_environment()
