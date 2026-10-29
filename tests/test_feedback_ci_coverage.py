"""Every feedback integration test is actually invoked by CI.

These tests need `--run-integration` and a live PostgreSQL, so they are
invisible to the default sweep: a new file is silently not run until someone
adds it to the workflow by hand. `test_feedback_read_access.py` shipped that
way -- the test that proves tenant isolation is enforced by the database had
only ever run on one machine.

The job also has to give each role its DSN. A missing one does not fail: the
tests read the variable, find it empty, and skip.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci-tests.yml").read_text()
# The job starts its database through this script, which writes the DSNs.
DATABASE_SCRIPT = "scripts/ci/start-recording-postgres.sh"
STARTUP = (ROOT / DATABASE_SCRIPT).read_text()
INTEGRATION_TESTS = sorted(
    {
        path.name
        for pattern in (
            "test_feedback_*.py",
            "test_recording_*database.py",
            "test_recording_retention_*.py",
        )
        for path in (ROOT / "tests" / "integration").glob(pattern)
    }
)


def test_there_are_feedback_integration_tests_to_check() -> None:
    """Guard the guard: a glob that matches nothing would pass silently."""
    assert INTEGRATION_TESTS


@pytest.mark.parametrize("name", INTEGRATION_TESTS)
def test_each_feedback_integration_test_is_named_in_the_workflow(name: str) -> None:
    assert (
        f"tests/integration/{name}" in WORKFLOW
    ), f"{name} is never run by CI; add it to the feedback-database job"


def test_the_job_starts_its_database_through_the_script() -> None:
    assert f"run: {DATABASE_SCRIPT}" in WORKFLOW


@pytest.mark.parametrize(
    "variable",
    [
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
        "SSF_FEEDBACK_OWNER_DATABASE_URL",
        "SSF_RECORDING_DATABASE_URL",
        "SSF_RECORDING_OWNER_DATABASE_URL",
        "SSF_RECORDING_RETENTION_DATABASE_URL",
        "SSF_RECORDING_REPLICA_DATABASE_URL",
    ],
)
def test_the_job_supplies_every_role_dsn(variable: str) -> None:
    """An absent DSN skips its tests rather than failing them."""
    assert f'echo "{variable}=' in STARTUP


@pytest.mark.parametrize(
    "migration",
    [
        "migrations/001_feedback",
        "migrations/002_feedback_roles",
        "migrations/003_feedback_reader",
        "migrations/004_feedback_dynamic",
        "recording/migrations/001_recording_keys",
        "recording/migrations/002_recovery_ceremony",
        "recording/migrations/003_recording_archive",
        "recording/migrations/004_recording_retention",
        "recording/migrations/005_recording_archive_access",
        "recording/migrations/006_recording_recovery_requests",
    ],
)
def test_the_job_checks_each_migration_applied(migration: str) -> None:
    """The roles these tests exercise only exist if their migration ran."""
    assert f"{migration}.sql" in STARTUP
