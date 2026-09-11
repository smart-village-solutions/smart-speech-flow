"""Alerts for the two maintenance passes (#305).

Everything here is a warning. Feedback is voluntary and its analytics are
optional; nothing in this group may page, for the same reason the
ssf-quality-telemetry group does not.

The retention alert is the exception in importance if not in severity: the
submission notice promises deletion after twelve months in ten languages, so
a retention pass that stops working is a commitment quietly going unmet.
"""

from pathlib import Path

import pytest
import yaml

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


class TestTheExpressionsUseMetricsThatExist:
    """A rule referring to a series nothing emits is silently never true."""

    EMITTED = {
        "ssf_feedback_reconciliation_total",
        "ssf_feedback_reconciliation_backlog",
        "ssf_feedback_retention_deleted_total",
        "ssf_feedback_maintenance_failures_total",
    }

    def test_every_referenced_ssf_metric_is_one_the_code_emits(self):
        import re

        for name, rule in _rules().items():
            for referenced in re.findall(r"ssf_feedback_[a-z_]+", rule["expr"]):
                assert referenced in self.EMITTED, f"{name} references {referenced}"

    def test_the_metric_names_match_the_maintenance_module(self):
        source = (ROOT / "services" / "api_gateway" / "feedback" / "maintenance.py").read_text()
        for metric in self.EMITTED:
            assert f'"{metric}"' in source

    def test_retention_alerts_on_absence_rather_than_on_a_failure_count(self):
        """A retention pass that never runs emits no failure metric at all,
        so counting failures would stay silent exactly when it matters."""
        expr = _rules()["FeedbackRetentionNotRunning"]["expr"]
        assert "ssf_feedback_retention_deleted_total" in expr
