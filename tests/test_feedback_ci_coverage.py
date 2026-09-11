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
INTEGRATION_TESTS = sorted(
    path.name for path in (ROOT / "tests" / "integration").glob("test_feedback_*.py")
)


def test_there_are_feedback_integration_tests_to_check() -> None:
    """Guard the guard: a glob that matches nothing would pass silently."""
    assert INTEGRATION_TESTS


@pytest.mark.parametrize("name", INTEGRATION_TESTS)
def test_each_feedback_integration_test_is_named_in_the_workflow(name: str) -> None:
    assert (
        f"tests/integration/{name}" in WORKFLOW
    ), f"{name} is never run by CI; add it to the feedback-database job"


@pytest.mark.parametrize(
    "variable",
    [
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
        "SSF_FEEDBACK_OWNER_DATABASE_URL",
    ],
)
def test_the_job_supplies_every_role_dsn(variable: str) -> None:
    """An absent DSN skips its tests rather than failing them."""
    assert f"{variable}:" in WORKFLOW


@pytest.mark.parametrize("migration", ["001_feedback", "002_feedback_roles", "003_feedback_reader"])
def test_the_job_checks_each_migration_applied(migration: str) -> None:
    """The roles these tests exercise only exist if their migration ran."""
    assert f"{migration}.sql" in WORKFLOW
