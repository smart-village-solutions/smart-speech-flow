"""Writer-health alerts and the scrape that makes them possible (task 3.3).

Delivery here is lossy by design: the SDK's BatchLogRecordProcessor drops on
overflow and does not surface that in `ssf_quality_telemetry_events_total`.
That blind spot is why task 2.1 cannot be decided yet, so the instrument that
closes it is part of this work rather than a follow-up.

The gap between what the gateway counted as queued and what the collector
counted as received *is* the SDK's drop. Neither number alone can show it.

Every collector metric named here was read from a running 0.159.0 collector's
:8888 endpoint, not from documentation.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "monitoring" / "alert_rules.yml"
PROMETHEUS = ROOT / "monitoring" / "prometheus.yml"
COLLECTOR = ROOT / "monitoring" / "otel-collector-config.yaml"

GROUP = "ssf-quality-telemetry"


def _rules() -> dict[str, dict]:
    """Empty rather than raising when the group is absent, so a deleted group
    fails these tests one by one instead of erroring the whole collection."""
    groups = yaml.safe_load(ALERTS.read_text())["groups"]
    group = next((g for g in groups if g["name"] == GROUP), None)
    return {rule["alert"]: rule for rule in group["rules"]} if group else {}


class TestTheCollectorIsScrapeable:
    def test_the_collector_exposes_its_internal_metrics_off_localhost(self):
        """The default binds localhost, which no other container can reach."""
        telemetry = yaml.safe_load(COLLECTOR.read_text())["service"]["telemetry"]
        reader = telemetry["metrics"]["readers"][0]["pull"]["exporter"]["prometheus"]
        assert reader["host"] == "0.0.0.0"
        assert reader["port"] == 8888

    def test_prometheus_scrapes_the_collector(self):
        config = yaml.safe_load(PROMETHEUS.read_text())
        jobs = {j["job_name"]: j for j in config["scrape_configs"]}
        assert "otel_collector" in jobs
        targets = jobs["otel_collector"]["static_configs"][0]["targets"]
        assert targets == ["otel-collector:8888"]

    @pytest.mark.parametrize(
        "compose",
        ["docker-compose.yml", "deploy/production/docker-compose.production.yml"],
    )
    def test_the_metrics_port_is_exposed_but_not_published(self, compose):
        """expose, never ports: the collector stays internal to the network."""
        service = yaml.safe_load((ROOT / compose).read_text())["services"]["otel-collector"]
        assert "8888" in [str(p) for p in service["expose"]]
        assert "ports" not in service


class TestWriterHealthAlerts:
    @pytest.mark.parametrize(
        "alert",
        [
            "QualityTelemetryExportFailing",
            "QualityTelemetryAttributeRejected",
            "QualityTelemetryEventsLostBeforeCollector",
            "QualityTelemetryClickHouseWritesFailing",
            "QualityTelemetryExporterQueueFilling",
            "QualityTelemetryCollectorRefusingRecords",
            "QualityTelemetryCollectorDown",
        ],
    )
    def test_the_alert_exists(self, alert):
        assert alert in _rules()

    def test_the_sdk_drop_is_measured_as_a_gap_not_a_counter(self):
        """There is no counter for it. The gateway counts what it queued and
        the collector counts what arrived; only the difference reveals a drop."""
        expr = _rules()["QualityTelemetryEventsLostBeforeCollector"]["expr"]
        assert 'ssf_quality_telemetry_events_total{outcome="emitted"}' in expr
        assert "otelcol_receiver_accepted_log_records" in expr

    def test_a_rejected_attribute_alerts_without_a_delay(self):
        """dropped_disallowed means the six places disagree -- a code defect
        that silently loses a field, not a transient condition to wait out."""
        rule = _rules()["QualityTelemetryAttributeRejected"]
        assert 'outcome="dropped_disallowed"' in rule["expr"]
        assert rule.get("for", "0m") in ("0m", None)

    @pytest.mark.parametrize("alert", sorted(_rules()))
    def test_every_alert_says_what_to_do(self, alert):
        annotations = _rules()[alert]["annotations"]
        assert annotations["summary"].strip()
        assert annotations["description"].strip()

    @pytest.mark.parametrize("alert", sorted(_rules()))
    def test_every_alert_is_labelled_as_telemetry(self, alert):
        labels = _rules()[alert]["labels"]
        assert labels["component"] == "quality-telemetry"
        assert labels["severity"] in ("warning", "critical")

    def test_telemetry_failure_is_never_critical(self):
        """Telemetry is optional; the gateway is not. A dead collector must not
        page anyone at 03:00 -- translation is unaffected by design."""
        severities = {a: r["labels"]["severity"] for a, r in _rules().items()}
        assert set(severities.values()) == {"warning"}, severities
