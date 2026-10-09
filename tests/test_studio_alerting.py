"""Alerts for Studio: failed live policy reads and stale display content.

Their firing behaviour is pinned by promtool in monitoring/alert_rules_test.yml
(run by tests/test_alert_rules_promtool.py); this file pins what promtool cannot
see: the group's shape, its severities and the outcome labels it relies on.
"""

from pathlib import Path

import yaml

from services.api_gateway.studio_content_metrics import OUTCOMES as CONTENT_OUTCOMES
from services.api_gateway.studio_policy_reads import OUTCOMES as READ_OUTCOMES

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "monitoring" / "alert_rules.yml"


def _rules() -> dict[str, dict]:
    groups = yaml.safe_load(ALERTS.read_text())["groups"]
    group = next((g for g in groups if g["name"] == "ssf-studio"), None)
    return {rule["alert"]: rule for rule in group["rules"]} if group else {}


def test_the_group_defines_its_three_alerts():
    assert set(_rules()) == {
        "StudioPolicyReadsFailing",
        "StudioPolicyGateUnbound",
        "StudioContentStale",
    }


def test_policy_read_failures_page_and_stale_content_does_not():
    rules = _rules()

    assert rules["StudioPolicyReadsFailing"]["labels"]["severity"] == "critical"
    assert rules["StudioPolicyGateUnbound"]["labels"]["severity"] == "critical"
    assert rules["StudioContentStale"]["labels"]["severity"] == "warning"
    assert {rule["labels"]["component"] for rule in rules.values()} == {"studio"}


def test_a_tenant_state_is_not_a_failure():
    expr = _rules()["StudioPolicyReadsFailing"]["expr"]

    assert 'outcome=~"unavailable|contract_error"' in expr
    assert "tenant_conflict" not in expr


def test_a_fresh_cached_answer_counts_as_healthy_content():
    expr = _rules()["StudioContentStale"]["expr"]

    assert 'outcome=~"live|cached"' in expr


def test_the_rules_use_only_outcomes_the_code_emits():
    assert {"unavailable", "contract_error"} <= set(READ_OUTCOMES)
    assert {"stale", "unavailable", "live", "cached"} <= set(CONTENT_OUTCOMES)


def test_every_annotation_says_what_to_check():
    for name, rule in _rules().items():
        assert "ssf-runtime" in rule["annotations"]["description"], name
    for name in ("StudioPolicyReadsFailing", "StudioContentStale"):
        assert "Studio answers from the gateway" in _rules()[name]["annotations"]["description"]
