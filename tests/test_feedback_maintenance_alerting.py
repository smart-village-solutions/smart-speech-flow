"""Alerts for the two maintenance passes (#305).

Everything here is a warning. Feedback is voluntary and its analytics are
optional; nothing in this group may page, for the same reason the
ssf-quality-telemetry group does not.

The retention alert is the exception in importance if not in severity: the
submission notice promises deletion after twelve months in ten languages, so
a retention pass that stops working is a commitment quietly going unmet.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from prometheus_client import CollectorRegistry

from services.api_gateway.feedback.maintenance import FeedbackMaintenanceMetrics

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "monitoring" / "alert_rules.yml"
GROUP = "ssf-feedback-maintenance"


def _rules() -> dict[str, dict]:
    groups = yaml.safe_load(ALERTS.read_text())["groups"]
    group = next((g for g in groups if g["name"] == GROUP), None)
    return {rule["alert"]: rule for rule in group["rules"]} if group else {}


class TestTheGroupExists:
    def test_the_feedback_maintenance_group_is_defined(self):
        assert _rules(), f"{GROUP} is missing from alert_rules.yml"

    def test_the_file_is_valid_yaml_with_every_rule_named(self):
        for name, rule in _rules().items():
            assert rule["expr"].strip(), name
            assert rule["annotations"]["summary"], name


class TestTheAlertsCoverEveryFailureMode:
    @pytest.mark.parametrize(
        "alert",
        [
            "FeedbackReconciliationBacklogGrowing",
            "FeedbackReconciliationFailing",
            "FeedbackRetentionNotRunning",
            "FeedbackMaintenanceJobFailing",
        ],
    )
    def test_the_alert_is_defined(self, alert):
        assert alert in _rules()

    def test_nothing_in_this_group_pages(self):
        for name, rule in _rules().items():
            assert rule["labels"]["severity"] == "warning", name

    def test_every_rule_is_attributed_to_the_feedback_component(self):
        for name, rule in _rules().items():
            assert rule["labels"]["component"] == "feedback", name


def _emitted_metric_names() -> set[str]:
    """Ask the code what it registers.

    A hand-kept list here is just a second place to forget, and forgetting
    means a rule that quietly never fires.
    """
    registry = CollectorRegistry()
    FeedbackMaintenanceMetrics(registry)

    names: set[str] = set()
    for metric in registry.collect():
        names.add(metric.name)
        if metric.type == "counter":
            names.add(f"{metric.name}_total")
    return names


class TestTheExpressionsUseMetricsThatExist:
    """A rule referring to a series nothing emits is silently never true."""

    def test_every_referenced_ssf_metric_is_one_the_code_emits(self):
        emitted = _emitted_metric_names()

        for name, rule in _rules().items():
            for referenced in re.findall(r"ssf_feedback_[a-z_]+", rule["expr"]):
                assert referenced in emitted, f"{name} references {referenced}"

    def test_retention_alerts_on_absence_rather_than_on_a_failure_count(self):
        """A retention pass that never runs emits no failure metric at all,
        so counting failures would stay silent exactly when it matters."""
        expr = _rules()["FeedbackRetentionNotRunning"]["expr"]
        assert "ssf_feedback_retention_deleted_total" in expr

    def test_a_pass_that_deletes_nothing_has_an_alert_of_its_own(self):
        """Both conditions must hold for an hour before warning about retention."""
        rule = _rules()["FeedbackRetentionDeletingNothing"]
        overdue, conjunction, deletions = rule["expr"].partition(" and ")

        assert overdue == "max(ssf_feedback_retention_overdue) > 0"
        assert conjunction == " and "
        assert deletions == "sum(increase(ssf_feedback_retention_deleted_total[6h])) == 0"
        assert rule["for"] == "1h"
        assert rule["labels"]["severity"] == "warning"
        assert rule["labels"]["component"] == "feedback"
        assert rule["annotations"]["summary"]
        assert rule["annotations"]["description"]

    @pytest.mark.parametrize(
        "overdue,deleted,expected",
        [
            (1, "0+0x36", 1),
            (0, "0+0x36", None),
            (1, "0+1x36", None),
            (1, "0+1x18 18+0x17", None),
        ],
        ids=[
            "overdue-with-no-deletions",
            "nothing-overdue",
            "deletions-making-progress",
            "deletions-earlier-in-the-six-hour-window",
        ],
    )
    def test_retention_alert_evaluates_both_conditions(self, tmp_path, overdue, deleted, expected):
        """absent() cannot catch it: the counter is exported as 0 from birth.

        Both arms are required. Overdue rows alone are normal while a backlog
        drains in batches; zero deletions alone are normal on a deployment
        younger than the retention period.
        """
        promtool = shutil.which("promtool")
        if promtool is None:
            pytest.skip("Prometheus promtool is required to evaluate retention alert behavior")
        expr = _rules()["FeedbackRetentionDeletingNothing"]["expr"]
        cases = {
            "evaluation_interval": "10m",
            "tests": [
                {
                    "interval": "10m",
                    "input_series": [
                        {
                            "series": "ssf_feedback_retention_overdue",
                            "values": f"{overdue}+0x36",
                        },
                        {"series": "ssf_feedback_retention_deleted_total", "values": deleted},
                    ],
                    "promql_expr_test": [
                        {
                            "expr": expr,
                            "eval_time": "6h",
                            "exp_samples": (
                                [] if expected is None else [{"labels": "{}", "value": expected}]
                            ),
                        }
                    ],
                }
            ],
        }
        case_file = tmp_path / "retention-alert.yml"
        case_file.write_text(yaml.safe_dump(cases))
        result = subprocess.run(
            [promtool, "test", "rules", str(case_file)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestNoAlertFiresOnOneReplicasStaleSeries:
    """Both gauges are per-replica, and only one replica works per pass.

    A gauge keeps its last value, so an unaggregated expression lets a replica
    that won a pass months ago -- and has lost every pass since -- hold an
    alert open against a backlog that drained long ago.
    """

    @pytest.mark.parametrize(
        "alert", ["FeedbackReconciliationBacklogGrowing", "FeedbackRetentionDeletingNothing"]
    )
    def test_the_gauge_is_aggregated_across_replicas(self, alert):
        expr = _rules()[alert]["expr"]

        for gauge in ("ssf_feedback_reconciliation_backlog", "ssf_feedback_retention_overdue"):
            if gauge in expr:
                assert f"max({gauge})" in expr, expr
