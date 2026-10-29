"""The retention worker's commands: exit codes, output, and no secret in any error."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.retention import __main__ as cli
from services.api_gateway.recording.retention.restore_guard import AuditHighWater, AuditMark
from services.api_gateway.recording.retention.store import PostgresRetentionStore
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from tests.recording_retention_fakes import TENANT, FakeRetentionStore

SECRET = "s3cr3t-" + "value"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "s3-retention.json").write_text(
        json.dumps({"access_key_id": "retention", "secret_access_key": SECRET})
    )
    (secrets / "database-password").write_text("db-" + "password\n")
    for name, value in {
        "SSF_RETENTION_SITE": "primary",
        "SSF_RETENTION_ENDPOINT": "http://seaweedfs.test:8333",
        "SSF_RETENTION_DATABASE_URL": "postgresql://ssf_recording_retention@db/ssf_recording",
        "SSF_RETENTION_SECRETS_DIR": str(secrets),
        "SSF_RETENTION_STATE_DIR": str(tmp_path / "state"),
    }.items():
        monkeypatch.setenv(name, value)
    return tmp_path


@pytest.fixture
def database(monkeypatch, tmp_path):
    store = FakeRetentionStore(positions={TENANT: 3})
    archive = FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31))
    monkeypatch.setattr(cli, "S3ArchiveStore", lambda client, credentials_for: archive)

    async def connect(settings):
        return store

    monkeypatch.setattr(PostgresRetentionStore, "connect", connect)
    return store


def test_once_prints_its_report_and_exits_0(environment, database, capsys):
    assert cli.main(["once"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "tenants": 1,
        "processed": 0,
        "failures": 0,
        "mismatches": 0,
        "halted": False,
        "shredded": 0,
        "versions_deleted": 0,
        "cleared": 0,
        "rows_deleted": 0,
        "swept": True,
    }
    assert len(database.beats) == 1
    assert database.closed is True


def test_bad_settings_exit_1_without_the_secret(environment, database, capsys):
    (environment / "secrets" / "s3-retention.json").write_text("{" + SECRET)
    assert cli.main(["once"]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.err + captured.out
    assert database.beats == []


def test_an_unreachable_database_exits_1_naming_only_the_failure(environment, monkeypatch, capsys):
    async def connect(settings):
        raise RecordingStorageUnavailable("the recording database is unavailable")

    monkeypatch.setattr(PostgresRetentionStore, "connect", connect)
    assert cli.main(["once"]) == 1
    assert capsys.readouterr().err.strip() == "retention: RecordingStorageUnavailable"


@pytest.mark.parametrize("argv", [["purge"], [], ["acknowledge-restore"]])
def test_usage_errors_exit_2(argv):
    with pytest.raises(SystemExit) as stopped:
        cli.main(argv)
    assert stopped.value.code == 2


def _halted(environment, *, reread: bool = True) -> None:
    """Tripped by a restore; the worker's re-read of the tenant done, or not yet."""
    with AuditHighWater(environment / "state").locked() as guard:
        guard.observe(False, False, {TENANT: AuditMark(9, "lost")}, advance=True)
        guard.observe(True, False, {}, advance=False)
        if reread:
            guard.rechecked(TENANT)


def test_acknowledging_a_restore_resumes_destructive_steps(environment, database, capsys):
    _halted(environment)

    assert cli.main(["acknowledge-restore", "--operator", "alice"]) == 0

    assert "alice" in capsys.readouterr().out
    with AuditHighWater(environment / "state").locked() as guard:
        assert guard.halted is False
        assert guard.marks == {TENANT: AuditMark(3, f"{TENANT}:3")}


def test_an_acknowledgement_waits_for_the_re_read(environment, database, capsys):
    _halted(environment, reread=False)
    assert cli.main(["acknowledge-restore", "--operator", "alice"]) == 1
    assert "not yet re-read" in capsys.readouterr().err
    assert AuditHighWater(environment / "state").halted is True


def test_an_acknowledgement_lists_what_the_restore_may_have_lost(environment, database, capsys):
    _halted(environment)
    database.conflicts = {
        TENANT: [
            ("c-held", "held_without_hold", None),
            ("c-extended", "locked_beyond_date", datetime(2027, 3, 1, tzinfo=timezone.utc)),
        ]
    }

    assert cli.main(["acknowledge-restore", "--operator", "alice"]) == 1
    err = capsys.readouterr().err
    assert f"held_without_hold {TENANT} c-held" in err
    assert f"locked_beyond_date {TENANT} c-extended until 2027-03-01T00:00:00+00:00" in err
    assert AuditHighWater(environment / "state").halted is True

    assert cli.main(["acknowledge-restore", "--operator", "alice", "--accept-conflicts"]) == 0
    assert AuditHighWater(environment / "state").halted is False


CONVERSATION = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
ERASE = ["erase", "--tenant", TENANT, "--conversation", CONVERSATION, "--reason", "court order"]


def _log(environment) -> list[dict]:
    path = environment / "state" / "erasures.log"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_an_erasure_is_logged_once_on_the_host(environment, database, capsys):
    assert cli.main([*ERASE, "--operator", "alice"]) == 0
    assert database.erased == [(TENANT, CONVERSATION, "alice", "court order")]
    [entry] = _log(environment)
    assert {key: entry[key] for key in ("tenant_id", "conversation_id", "operator", "reason")} == {
        "tenant_id": TENANT,
        "conversation_id": CONVERSATION,
        "operator": "alice",
        "reason": "court order",
    }
    assert entry["decision_id"] == "decision-1"
    mode = (environment / "state" / "erasures.log").stat().st_mode & 0o777
    assert mode == 0o600
    assert "decision-1" in capsys.readouterr().out


def test_erase_runs_on_the_primary_only(environment, database, monkeypatch, capsys):
    monkeypatch.setenv("SSF_RETENTION_SITE", "replica")
    assert cli.main([*ERASE, "--operator", "alice"]) == 2
    assert cli.main(["replay-erasures", "--operator", "alice"]) == 2
    assert "primary site only" in capsys.readouterr().err
    assert database.erased == []


def test_a_refused_erasure_exits_1_and_logs_nothing(environment, database, capsys):
    database.erase_refusals = {CONVERSATION: "legal_hold_set"}
    assert cli.main([*ERASE, "--operator", "alice"]) == 1
    assert "legal_hold_set" in capsys.readouterr().err
    assert not (environment / "state" / "erasures.log").exists()


@pytest.mark.parametrize(
    "argv",
    [
        [*ERASE[:4], "not-a-uuid", "--reason", "r", "--operator", "a"],
        [*ERASE[:6], "", "--operator", "a"],
        [*ERASE[:6], "x" * 501, "--operator", "a"],
    ],
)
def test_a_malformed_erasure_is_refused_before_the_database(environment, database, argv):
    assert cli.main(argv) == 1
    assert database.erased == []


def test_an_erasure_that_cannot_be_logged_exits_3_with_the_line(environment, database, capsys):
    (environment / "state").write_text("not a directory")
    assert cli.main([*ERASE, "--operator", "alice"]) == 3
    err = capsys.readouterr().err
    assert err.startswith("erasure committed but not logged: {")
    assert json.loads(err.split(": ", 1)[1])["decision_id"] == "decision-1"


def test_a_replay_erases_what_a_restore_brought_back(environment, database, capsys):
    restored, gone, done = (
        CONVERSATION,
        "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b",
        "2f8e4d3c-1a0b-4f9e-b8c7-6b5a4f3e2d1c",
    )
    for conversation in (restored, gone, done):
        assert cli.main([*ERASE[:4], conversation, *ERASE[5:], "--operator", "alice"]) == 0
    database.erased.clear()
    database.erase_refusals = {gone: "no_conversation", done: "conversation_shredded"}
    capsys.readouterr()

    assert cli.main(["replay-erasures", "--operator", "bob"]) == 0

    assert database.erased == [(TENANT, restored, "bob", "replay: court order")]
    assert capsys.readouterr().out.strip() == "replayed 1, skipped 2, refused 0"
    assert len(_log(environment)) == 3


def test_a_replay_refused_by_a_hold_exits_1_naming_it(environment, database, capsys):
    assert cli.main([*ERASE, "--operator", "alice"]) == 0
    database.erase_refusals = {CONVERSATION: "legal_hold_set"}
    assert cli.main(["replay-erasures", "--operator", "bob"]) == 1
    captured = capsys.readouterr()
    assert f"refused {CONVERSATION}: legal_hold_set" in captured.err
    assert "refused 1" in captured.out


def test_a_replay_with_no_log_replays_nothing(environment, database, capsys):
    assert cli.main(["replay-erasures", "--operator", "bob"]) == 0
    assert capsys.readouterr().out.strip() == "replayed 0, skipped 0, refused 0"


def test_a_corrupt_log_stops_the_replay_before_any_erasure(environment, database):
    (environment / "state").mkdir()
    (environment / "state" / "erasures.log").write_text("{broken\n")
    assert cli.main(["replay-erasures", "--operator", "bob"]) == 1
    assert database.erased == []
