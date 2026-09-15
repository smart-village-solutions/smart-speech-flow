"""#220: a stopped model service must raise an alert.

The *ServiceDown rules match `<svc>_health_status == 0`, a metric scraped from
the service itself. When the container stops the series disappears rather than
going to zero, so the expression matches nothing and the alert never fires.
Every scrape-failure rule here is the companion that does fire.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "monitoring" / "alert_rules.yml"
PROMETHEUS = ROOT / "monitoring" / "prometheus.yml"

MODEL_SERVICES = ("asr", "translation", "tts")

GROUP = "ssf-service-health"

# The gateway gets 1m because its failure is a total outage; the model
# services get 2m to ride out a restart. A test that cannot tell these apart
# would let the two get swapped silently.
EXPECTED_FOR = {"asr": "2m", "translation": "2m", "tts": "2m", "api_gateway": "1m"}


def _rules() -> dict[str, dict]:
    """Scoped to one group on purpose.

    Flattening every group into one name-keyed dict lets a duplicate alert name
    elsewhere in the file overwrite these silently, and proves nothing about
    where the rules actually live.
    """
    groups = yaml.safe_load(ALERTS.read_text())["groups"]
    group = next((g for g in groups if g["name"] == GROUP), None)
    return {rule["alert"]: rule for rule in group["rules"]} if group else {}


def _scrape_jobs() -> set[str]:
    config = yaml.safe_load(PROMETHEUS.read_text())
    return {job["job_name"] for job in config["scrape_configs"]}


class TestEveryModelServiceIsScraped:
    @pytest.mark.parametrize("service", MODEL_SERVICES + ("api_gateway",))
    def test_the_job_exists(self, service: str):
        """An up{job=...} alert on a job Prometheus does not scrape is inert."""
        assert service in _scrape_jobs()


class TestScrapeFailureRaisesAnAlert:
    @pytest.mark.parametrize("service", MODEL_SERVICES + ("api_gateway",))
    def test_a_scrape_down_rule_exists(self, service: str):
        expected = f'up{{job="{service}"}} == 0'
        exprs = [rule["expr"].strip() for rule in _rules().values()]
        assert expected in exprs, (
            f"no rule matches {expected}; stopping the {service} container "
            "would raise nothing"
        )

    @pytest.mark.parametrize("service,expected_for", EXPECTED_FOR.items())
    def test_it_is_critical_and_fires_within_the_expected_wait(
        self, service: str, expected_for: str
    ):
        rule = next(
            r for r in _rules().values()
            if r["expr"].strip() == f'up{{job="{service}"}} == 0'
        )
        assert rule["labels"]["severity"] == "critical"
        assert rule["labels"]["service"] == service
        assert rule["for"] == expected_for, (
            f"{rule['alert']} waits {rule['for']}, expected {expected_for}; "
            "a dead service should not wait longer than its outage warrants"
        )


class TestTheHealthStatusRulesAreKeptButNotRelieduponAlone:
    """The <svc>_health_status rules stay: they catch a service that answers
    but reports itself unhealthy -- a different failure from the container
    being gone, which up{job=...} cannot detect."""

    @pytest.mark.parametrize(
        "alert_name",
        ("ASRServiceDown", "TranslationServiceDown", "TTSServiceDown"),
    )
    def test_the_health_rule_still_exists(self, alert_name: str):
        assert alert_name in _rules()


class TestTheRulesLiveWhereTheyAreLookedFor:
    @pytest.mark.parametrize(
        "alert_name",
        (
            "ASRScrapeDown",
            "TranslationScrapeDown",
            "TTSScrapeDown",
            "APIGatewayScrapeDown",
        ),
    )
    def test_the_scrape_rule_is_in_the_service_health_group(self, alert_name: str):
        assert alert_name in _rules(), f"{alert_name} is not in the {GROUP} group"


class TestEveryRuleIsDocumented:
    def test_each_alert_carries_a_runbook_annotation(self):
        """runbook_url, not runbook: Alertmanager and Grafana templates render
        the former and silently ignore the latter, so the link an operator
        needs at 03:00 would never appear."""
        missing = [
            name for name, rule in _rules().items()
            if not rule.get("annotations", {}).get("runbook_url")
            and name.endswith("ScrapeDown")
        ]
        assert not missing, f"no runbook_url annotation on {missing}"
