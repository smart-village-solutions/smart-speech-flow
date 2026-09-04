"""Grafana must reach ClickHouse over the compose network, never a host port.

Assertions run against `docker compose config` for the local stack (the
resolved configuration a deploy actually gets), and against the production
Compose file's own text, mirroring
tests/test_otel_collector_compose_configuration.py.
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
DATASOURCES_CONFIG = (
    ROOT / "monitoring" / "grafana-provisioning" / "datasources" / "datasources.yml"
)
DASHBOARD = ROOT / "monitoring" / "grafana-dashboards" / "ssf-telemetry.json"
GITIGNORE = ROOT / ".gitignore"


def _services() -> dict:
    # All nine variables are required: `docker compose config` fails outright if
    # any interpolation is unsatisfied, including Keycloak's. Mirrors the pattern
    # in tests/test_otel_collector_compose_configuration.py.
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as env_file:
        env_file.write("CLICKHOUSE_DB=ssf_analytics_test\n")
        env_file.write("CLICKHOUSE_USER=ssf_telemetry_test\n")
        env_file.write("CLICKHOUSE_PASSWORD=test-only-password\n")
        env_file.write("KEYCLOAK_DB_NAME=keycloak_test\n")
        env_file.write("KEYCLOAK_DB_USER=keycloak_test_user\n")
        env_file.write("KEYCLOAK_DB_PASSWORD=test-only-db-password\n")
        env_file.write("KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=bootstrap_admin\n")
        env_file.write("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=test-only-admin-password\n")
        env_file.write("KEYCLOAK_HOSTNAME=auth.test.example\n")
    try:
        # -f pins to the committed base file only: a developer's local, untracked
        # docker-compose.override.yml (see CLAUDE.md) may gate monitoring services
        # behind a profile for convenience, which must not change what this test
        # verifies about the committed configuration CI actually sees.
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "--env-file",
                env_file.name,
                "config",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(env_file.name)
    return yaml.safe_load(result.stdout)["services"]


def _production() -> dict:
    return yaml.safe_load(
        (ROOT / "deploy" / "production" / "docker-compose.production.yml").read_text()
    )["services"]


def _production_env(service: str) -> dict:
    return dict(
        entry.split("=", 1)
        for entry in _production()[service]["environment"]
        if "=" in entry
    )


def _datasources() -> dict:
    return yaml.safe_load(DATASOURCES_CONFIG.read_text())


def _clickhouse_datasource() -> dict:
    matches = [d for d in _datasources()["datasources"] if d["uid"] == "clickhouse-ssf"]
    assert matches, _datasources()["datasources"]
    return matches[0]


def _plugin_pin(env: dict) -> tuple[str, str]:
    """Split GF_INSTALL_PLUGINS into (id, version).

    Grafana's entrypoint word-splits each comma-separated entry into
    `grafana cli plugins install <id> <version>`, so a version is pinned by a
    space, not a colon or an `@`.
    """
    parts = env["GF_INSTALL_PLUGINS"].split()

    assert len(parts) == 2, f"plugin version not pinned: {env['GF_INSTALL_PLUGINS']!r}"
    return parts[0], parts[1]


def test_local_grafana_installs_a_pinned_clickhouse_plugin() -> None:
    """Every production image is pinned by digest; a plugin fetched from
    grafana.com at each container start must be pinned too, or a restart
    installs a version the dashboard was never verified against."""
    plugin_id, version = _plugin_pin(_services()["grafana"]["environment"])

    assert plugin_id == "grafana-clickhouse-datasource"
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


def test_local_grafana_has_clickhouse_credentials() -> None:
    env = _services()["grafana"]["environment"]

    assert env["CLICKHOUSE_DB"] == "ssf_analytics_test"
    assert env["CLICKHOUSE_USER"] == "ssf_telemetry_test"
    assert env["CLICKHOUSE_PASSWORD"] == "test-only-password"


def test_local_grafana_gets_no_new_public_surface() -> None:
    """Wiring the datasource must not add a host port or Traefik route to ClickHouse."""
    clickhouse = _services()["clickhouse"]

    assert clickhouse.get("ports") is None
    assert clickhouse.get("labels") is None


def test_production_grafana_installs_the_same_pinned_plugin() -> None:
    """Drift between the two stacks means production runs a plugin version
    nobody verified locally."""
    assert _plugin_pin(_production_env("grafana")) == _plugin_pin(
        _services()["grafana"]["environment"]
    )


def test_production_grafana_has_clickhouse_credentials() -> None:
    env = _production_env("grafana")

    assert {"CLICKHOUSE_DB", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"} <= set(env)


def test_production_clickhouse_still_has_no_public_surface() -> None:
    clickhouse = _production()["clickhouse"]

    assert clickhouse.get("ports") is None
    assert clickhouse.get("labels") is None


def test_clickhouse_datasource_is_provisioned_with_the_right_settings() -> None:
    datasource = _clickhouse_datasource()

    assert datasource["type"] == "grafana-clickhouse-datasource"
    assert datasource["access"] == "proxy"
    assert datasource["editable"] is False
    assert datasource["jsonData"] == {
        "host": "clickhouse",
        "port": 9000,
        "protocol": "native",
        "defaultDatabase": "$CLICKHOUSE_DB",
        "username": "$CLICKHOUSE_USER",
    }
    assert datasource["secureJsonData"] == {"password": "$CLICKHOUSE_PASSWORD"}


def test_reprovisioning_removes_a_stale_clickhouse_datasource_first() -> None:
    """Prometheus and Loki are both deleted-then-recreated; ClickHouse must match."""
    names = {entry["name"] for entry in _datasources()["deleteDatasources"]}

    assert "ClickHouse" in names


def test_dashboard_json_is_valid() -> None:
    json.loads(DASHBOARD.read_text())


def _clickhouse_queries() -> list[str]:
    """Only the ClickHouse targets. The dashboard also carries Prometheus
    panels for writer health, which have an expr and no rawSql."""
    dashboard = json.loads(DASHBOARD.read_text())
    return [
        " ".join(target["rawSql"].split())
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
        if target.get("rawSql")
    ]


def test_every_raw_tier_read_deduplicates() -> None:
    """quality_events is a ReplacingMergeTree: undeduplicated reads double-count
    rows still awaiting a background merge.

    The gold tier is deliberately exempt. quality_events_daily is an
    AggregatingMergeTree whose counts are uniqExact over event_id, so it is
    already idempotent and FINAL there would only cost a merge pass.
    """
    queries = _clickhouse_queries()
    assert queries, "dashboard has no ClickHouse queries"

    # Per FROM clause, not per query: the retention panel unions both tiers, so
    # asking whether the whole statement mentions FINAL answers nothing.
    reads = [
        (match.group(1), bool(match.group(2)))
        for sql in queries
        for match in re.finditer(
            r"FROM\s+(quality_events_daily|quality_events)\b(\s+FINAL)?", sql
        )
    ]
    assert reads, "no reads of either tier"

    for table, deduplicated in reads:
        assert deduplicated is (table == "quality_events"), (table, deduplicated)


def test_every_windowed_read_uses_the_dashboard_time_range() -> None:
    """A panel that ignores the picker reports the whole retention window and
    silently disagrees with every other panel on screen.

    Retention verification is exempt by design: its whole purpose is to find the
    oldest surviving row, which a time filter would hide. The gold tier is
    keyed on event_date, a Date, so it takes the date-filter macro instead --
    exempting it entirely meant it scanned all thirteen months on every refresh
    and drew an x-axis the time picker did not control.
    """
    for sql in _clickhouse_queries():
        if "oldest_row" in sql:
            continue
        if "quality_events_daily" in sql and "uniqExactMerge" in sql:
            assert "$__dateFilter(event_date)" in sql, sql
            continue
        assert "$__timeFilter(emitted_at_utc)" in sql, sql


def test_no_panel_counts_the_untyped_default_as_a_failure() -> None:
    """error_code defaults to '' for rows written before migration 002. Counting
    that as a failure makes "Failed Attempts" equal total attempts, which reads
    as a total outage rather than the schema problem it actually is."""
    for sql in _clickhouse_queries():
        if "error_code" not in sql:
            continue
        assert "error_code != 'none'" not in sql, sql


def test_every_gold_read_names_the_event_type_it_summarises() -> None:
    """The gold tier's latency states are the refinement attempt's.

    A `translation_message` row reaches it too and contributes a correct daily
    count under its own event_type and a zero to every latency state, so a gold
    query that does not filter on event_type averages a real population with a
    column of zeros. Verified live: gold reported translation_message with
    events = 1 and latency_ms_avg = 0.
    """
    for sql in _clickhouse_queries():
        if "quality_events_daily" not in sql or "oldest_row" in sql:
            continue
        assert "event_type =" in sql, sql


def test_message_panels_read_the_message_event_only() -> None:
    """Every duration column is shared between the two event types, and a
    refinement row's total_duration_ms is zero."""
    for sql in _clickhouse_queries():
        if "total_duration_ms" not in sql:
            continue
        assert "event_type = 'translation_message'" in sql, sql


def test_no_panel_reads_a_message_stage_duration_without_excluding_zero() -> None:
    """A text message has no ASR stage and a run with refinement off has no
    refinement stage. Both store 0, and averaging those in reports every stage
    as faster than it is."""
    stages = (
        "asr_duration_ms",
        "translation_duration_ms",
        "refinement_duration_ms",
        "tts_duration_ms",
    )
    for sql in _clickhouse_queries():
        for stage in stages:
            if f"({stage})" not in sql:
                continue
            assert f"nullIf({stage}, 0)" in sql, (stage, sql)


def test_lifecycle_panels_read_the_lifecycle_event_only() -> None:
    """`session_duration_ms` and `message_count` are 0 on every other event
    type, so a panel that omits the filter averages real sessions against a
    column of zeros."""
    for sql in _clickhouse_queries():
        if "session_duration_ms" not in sql and "message_count" not in sql:
            continue
        assert "event_type = 'session_lifecycle'" in sql, sql


def test_no_panel_reads_a_session_duration_outside_a_terminated_row() -> None:
    """`created` and `activated` rows report a duration of 0 by construction --
    the session has not ended, so there is nothing to measure yet."""
    for sql in _clickhouse_queries():
        if "session_duration_ms" not in sql and "avg(message_count)" not in sql:
            continue
        assert "lifecycle_phase = 'terminated'" in sql, sql


def test_the_dashboard_reads_both_medallion_tiers() -> None:
    """A gold tier nothing reads is a tier nobody notices has stopped filling."""
    queries = _clickhouse_queries()
    assert any("quality_events_daily" in sql for sql in queries)
    assert any("quality_events FINAL" in sql for sql in queries)


def test_writer_health_comes_from_prometheus_not_clickhouse() -> None:
    """ClickHouse cannot report events that never reached it."""
    dashboard = json.loads(DASHBOARD.read_text())
    exprs = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
        if target.get("expr")
    ]
    assert any("ssf_quality_telemetry_events_total" in e for e in exprs)
    assert any("otelcol_receiver_accepted_log_records" in e for e in exprs)


def test_gitignore_excludes_the_plugin_install_directory() -> None:
    lines = GITIGNORE.read_text().splitlines()

    assert "monitoring/grafana/plugins/" in lines


def test_gitignore_does_not_blanket_ignore_the_grafana_bind_mount() -> None:
    """monitoring/grafana/alerting/1/__default__.tmpl is a tracked file; a
    wholesale ignore of monitoring/grafana would silently untrack it."""
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "monitoring/grafana/alerting/1/__default__.tmpl",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout

    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "monitoring/grafana/plugins/grafana-clickhouse-datasource/plugin.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
