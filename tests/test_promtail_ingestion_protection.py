"""The log collector must not ingest the monitoring stack's own retry noise."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMTAIL = ROOT / "monitoring" / "promtail-config.yaml"
LOKI = ROOT / "monitoring" / "loki-config.yaml"
PROMETHEUS = ROOT / "monitoring" / "prometheus.yml"
ALERTS = ROOT / "monitoring" / "alert_rules.yml"


def test_monitoring_log_feedback_is_prevented_and_observable() -> None:
    """Loki queries and collector retries must neither recurse nor go unseen."""
    promtail = yaml.safe_load(PROMTAIL.read_text())
    relabel_rules = promtail["scrape_configs"][0]["relabel_configs"]

    assert {
        "source_labels": ["__meta_docker_container_name"],
        "regex": r"/(.+-)?(loki|promtail)(-[0-9]+)?",
        "action": "drop",
    } in relabel_rules

    loki = yaml.safe_load(LOKI.read_text())
    assert loki["limits_config"]["query_timeout"] == "5m"
    assert "querier" not in loki

    prometheus = yaml.safe_load(PROMETHEUS.read_text())
    scrape_jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert scrape_jobs["promtail"]["static_configs"][0]["targets"] == ["promtail:9080"]
    for compose in (
        ROOT / "docker-compose.yml",
        ROOT / "deploy/production/docker-compose.production.yml",
    ):
        service = yaml.safe_load(compose.read_text())["services"]["promtail"]
        assert "9080" in [str(port) for port in service["expose"]]
        assert "ports" not in service

    groups = yaml.safe_load(ALERTS.read_text())["groups"]
    rules = {
        rule["alert"]: rule
        for group in groups
        if group["name"] == "ssf-monitoring-ingestion"
        for rule in group["rules"]
    }
    assert "PromtailPushRateLimited" in rules
    assert 'status_code="429"' in rules["PromtailPushRateLimited"]["expr"]
    assert "PromtailDroppedEntries" in rules
    assert "promtail_dropped_entries_total" in rules["PromtailDroppedEntries"]["expr"]
