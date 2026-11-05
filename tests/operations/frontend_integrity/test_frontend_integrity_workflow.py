"""The monitor runs off the hour, is off until configured, and keeps server text out of shell (#620, spec §6)."""

import json
from pathlib import Path

import yaml

from scripts.frontend_integrity.__main__ import main
from tests.operations.frontend_integrity.frontend_integrity_fakes import (
    FrontendServer,
    SiteBehaviour,
    fingerprint,
    write_site,
)

WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "frontend-integrity-monitor.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _script(job: str) -> str:
    return "\n".join(step.get("run", "") for step in _workflow()["jobs"][job]["steps"])


def test_it_runs_every_fifteen_minutes_off_the_full_hour():
    assert _workflow()[True]["schedule"] == [{"cron": "7,22,37,52 * * * *"}]


def test_the_scheduled_check_is_off_until_the_url_is_set():
    assert "vars.FRONTEND_MONITOR_URL != ''" in _workflow()["jobs"]["check"]["if"]


def test_the_check_compares_with_the_recorded_fingerprint_on_main():
    assert "--manifest deploy/production/frontend-manifest.json" in _script("check")


def test_permissions_are_the_least_each_job_needs():
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}
    for job in ("check", "self-test"):
        assert workflow["jobs"][job]["permissions"] == {"contents": "read", "issues": "write"}


def test_no_expression_is_expanded_inside_a_shell_script():
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")


def test_the_self_test_opens_its_issue_under_its_own_label():
    assert "--label bundle-integrity-test" in _script("self-test")


def test_check_writes_a_verdict_for_the_alert_step(tmp_path):
    root = write_site(tmp_path / "site")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "current": fingerprint(root), "previous": None}))
    out = tmp_path / "verdict.json"
    with FrontendServer(SiteBehaviour(root)) as base:
        assert main(["check", "--url", base, "--manifest", str(manifest), "--out", str(out)]) == 0

    assert json.loads(out.read_text())["outcome"] == "match"
