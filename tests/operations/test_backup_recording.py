"""The daily ssf_recording dump: kept 14 days, pruned first, never in the tiers (spec §16)."""

from __future__ import annotations

import os
import stat
import time

from tests.operations.test_production_scripts import ROOT, run_script

FAKE_DOCKER = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
arguments="$*"
if [[ "$arguments" == *"pg_database"* ]]; then
  [[ "${FAKE_RECORDING_DB:-yes}" == "yes" ]] && printf '1\\n'
  exit 0
elif [[ "$arguments" == *"pg_dump"* ]]; then
  [[ "${FAKE_DUMP_FAILS:-no}" == "yes" ]] && { printf 'connection refused\\n' >&2; exit 1; }
  printf 'recording dump\\n'
fi
"""


def _fixture(tmp_path) -> tuple[dict[str, str], os.PathLike]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text(FAKE_DOCKER)
    (fake_bin / "docker").chmod(0o755)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("")
    backups = tmp_path / "backups" / "recording"
    return (
        {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "SSF_PROJECT_ROOT": str(project),
            "SSF_RECORDING_BACKUP_ROOT": str(backups),
        },
        backups,
    )


def _aged(backups, name: str, days: float):
    path = backups / name
    path.write_text("old")
    moment = time.time() - days * 86400
    os.utime(path, (moment, moment))
    return path


def test_a_dump_is_written_privately_and_complete(tmp_path):
    environment, backups = _fixture(tmp_path)
    result = run_script("scripts/backup-recording.sh", environment=environment)
    assert result.returncode == 0, result.stderr
    [dump] = list(backups.iterdir())
    assert dump.name.startswith("ssf-recording-") and dump.name.endswith(".sql.gz")
    assert stat.S_IMODE(dump.stat().st_mode) == 0o600
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    assert 'pg_dump -U "$POSTGRES_USER" -d ssf_recording' in (tmp_path / "docker.log").read_text()


def test_dumps_older_than_14_days_go_and_younger_ones_stay(tmp_path):
    environment, backups = _fixture(tmp_path)
    backups.mkdir(parents=True)
    old = _aged(backups, "ssf-recording-old.sql.gz", 15)
    pre_migration = _aged(backups, "pre-004.sql.gz", 14.1)
    killed = _aged(backups, "ssf-recording-killed.sql.gz.partial", 15)
    recent = _aged(backups, "ssf-recording-recent.sql.gz", 13)
    unrelated = _aged(backups, "notes.txt", 30)
    assert run_script("scripts/backup-recording.sh", environment=environment).returncode == 0
    assert not old.exists() and not pre_migration.exists() and not killed.exists()
    assert recent.exists() and unrelated.exists()


def test_a_failing_dump_still_prunes_and_leaves_no_partial_file(tmp_path):
    environment, backups = _fixture(tmp_path)
    backups.mkdir(parents=True)
    old = _aged(backups, "ssf-recording-old.sql.gz", 15)
    environment["FAKE_DUMP_FAILS"] = "yes"
    result = run_script("scripts/backup-recording.sh", environment=environment)
    assert result.returncode != 0
    assert not old.exists()
    assert list(backups.iterdir()) == []


def test_a_host_without_the_recording_database_writes_nothing(tmp_path):
    environment, backups = _fixture(tmp_path)
    environment["FAKE_RECORDING_DB"] = "no"
    result = run_script("scripts/backup-recording.sh", environment=environment)
    assert result.returncode == 0, result.stderr
    assert "does not exist" in result.stdout
    assert list(backups.iterdir()) == []
    assert "pg_dump" not in (tmp_path / "docker.log").read_text()


def test_the_tiered_backups_never_hold_the_recording_database():
    tiered = (ROOT / "scripts/backup-production.sh").read_text()
    assert "ssf_recording" not in tiered
    assert "backup-recording" not in tiered
