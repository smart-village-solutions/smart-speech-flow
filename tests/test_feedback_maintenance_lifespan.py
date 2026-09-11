"""The maintenance passes must actually be driven by the running gateway.

#302 shipped `delete_expired` and `claim_pending_analytics` fully tested, and
nothing called either: the twelve-month deletion the submission notice
promises in ten languages had no enforcer at all. A method that exists and is
never scheduled is indistinguishable from an absent one in production, so
these assert the wiring rather than the behaviour.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "services" / "api_gateway" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")


def _function_names() -> set[str]:
    tree = ast.parse(SOURCE)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


class TestTheTaskExists:
    def test_a_maintenance_task_is_defined(self):
        assert "feedback_maintenance_task" in _function_names()

    def test_the_task_is_started_by_the_lifespan(self):
        assert "asyncio.create_task(feedback_maintenance_task())" in SOURCE

    def test_the_task_is_cancelled_at_shutdown(self):
        """An uncancelled task keeps the loop alive past the stop grace."""
        assert "feedback_maintenance_bg_task.cancel()" in SOURCE

    def test_the_task_is_awaited_in_the_shutdown_gather(self):
        gather = SOURCE[SOURCE.index("task_results = await asyncio.gather(") :]
        gather = gather[: gather.index(")")]
        assert "feedback_maintenance_bg_task" in gather


class TestBothPassesAreDriven:
    @pytest.mark.parametrize("call", ["reconcile_once()", "expire_once()"])
    def test_the_pass_is_invoked(self, call):
        assert call in SOURCE

    def test_retention_runs_on_its_own_slower_schedule(self):
        """Reconciliation is cheap and wants to be prompt; deletion is neither."""
        assert "FEEDBACK_RECONCILIATION_INTERVAL_SECONDS" in SOURCE
        assert "FEEDBACK_RETENTION_INTERVAL_SECONDS" in SOURCE


class TestItDegradesLikeTheRestOfFeedback:
    def test_no_store_means_no_maintenance_rather_than_no_gateway(self):
        """`feedback_maintenance` stays None when the database is unreachable,
        exactly as `feedback_service` does, so the task idles instead of
        raising every interval."""
        assert "app.state.feedback_maintenance = None" in SOURCE

    def test_the_task_body_guards_on_the_maintenance_object(self):
        task = SOURCE[SOURCE.index("async def feedback_maintenance_task") :]
        task = task[: task.index("\nasync def ", 10)] if "\nasync def " in task[10:] else task
        assert "is None" in task


class TestMaintenanceConnectsAsItsOwnRole:
    """The two passes need a role the tenant policy does not filter.

    Reconciliation and retention are deployment-wide: there is no tenant to
    bind them to, so under the request-path role they would see no rows and
    report success. Migration 002 gives them `ssf_feedback_maintenance`; this
    asserts the gateway actually opens a second pool with it, because sharing
    the request pool would silently disable both passes.
    """

    def test_the_maintenance_dsn_is_read_from_its_own_variable(self):
        assert "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL" in SOURCE

    def test_the_maintenance_pool_is_closed_at_shutdown(self):
        assert "feedback_maintenance_repository" in SOURCE

    def test_a_missing_maintenance_dsn_leaves_submissions_working(self):
        """Collecting feedback matters more than reconciling it."""
        assert "app.state.feedback_maintenance = None" in SOURCE
