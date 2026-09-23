"""Runs promtool's own unit tests for the alert rules (issue: PR #409 review).

`monitoring/alert_rules_test.yml` pins down rule behaviour promtool cannot
verify by parsing alone -- see its header comment. Nothing in the test suite
executed it, so a broken rule expression could ship without the suite
noticing. This mirrors the skip-if-unavailable pattern in
tests/test_feedback_maintenance_alerting.py.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

MONITORING_DIR = Path(__file__).resolve().parents[1] / "monitoring"


def test_promtool_accepts_the_alert_rules_test_cases():
    promtool = shutil.which("promtool")
    if promtool is None:
        pytest.skip("Prometheus promtool is required to evaluate the alert rule tests")

    result = subprocess.run(
        [promtool, "test", "rules", "alert_rules_test.yml"],
        cwd=MONITORING_DIR,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
