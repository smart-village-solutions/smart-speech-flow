"""The collector must stay internal, and its allowlist must not drift.

Assertions run against `docker compose config` — the resolved configuration a
deploy actually gets — not against the compose file's text.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from services.api_gateway.quality_telemetry import ALLOWED_ATTRIBUTE_KEYS

ROOT = Path(__file__).parents[1]
COLLECTOR_CONFIG = ROOT / "monitoring" / "otel-collector-config.yaml"
MIGRATION_DIR = ROOT / "deploy" / "clickhouse"
MIGRATIONS = MIGRATION_DIR / "migrations"

# Resource attributes are a separate namespace from log attributes: the log
# allowlist does not filter them, so they need their own agreed set.
ALLOWED_RESOURCE_KEYS = {
    "service.name",
    "service.version",
    "deployment.environment.name",
}


def _services() -> dict:
    # All nine variables are required: `docker compose config` fails outright if
    # any interpolation is unsatisfied, including Keycloak's. Mirrors the pattern
    # in tests/test_keycloak_compose_configuration.py.
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
        result = subprocess.run(
            ["docker", "compose", "--env-file", env_file.name, "config"],
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
        entry.split("=", 1) for entry in _production()[service]["environment"] if "=" in entry
    )


def _production_env_example() -> dict:
    return dict(
        line.split("=", 1)
        for line in (ROOT / "deploy" / "production" / "production.env.example")
        .read_text()
        .splitlines()
        if "=" in line and not line.startswith("#")
    )


def _interpolation_default(value: str) -> str:
    """Resolve `${VAR:-default}` to `default`; return a literal unchanged."""
    if value.startswith("${") and ":-" in value:
        return value.split(":-", 1)[1].rstrip("}")
    return value


def _env_example() -> dict:
    return dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def _collector_config() -> dict:
    return yaml.safe_load(COLLECTOR_CONFIG.read_text())


def test_collector_is_pinned_and_internal() -> None:
    service = _services()["otel-collector"]

    assert service["image"] == "otel/opentelemetry-collector-contrib:0.159.0"
    assert service["restart"] == "always"
    assert service.get("ports") is None
    assert service.get("labels") is None


def test_collector_config_is_mounted_read_only() -> None:
    mounts = _services()["otel-collector"]["volumes"]
    assert any(m["target"] == "/etc/otelcol-contrib/config.yaml" and m["read_only"] for m in mounts)


def test_clickhouse_applies_the_repository_migrations_on_first_boot() -> None:
    """Without this mount nothing creates quality_events on a fresh deploy."""
    mounts = _services()["clickhouse"]["volumes"]
    initdb = [m for m in mounts if m["target"] == "/docker-entrypoint-initdb.d"]

    assert initdb, mounts
    assert initdb[0]["read_only"]
    assert initdb[0]["source"] == str(MIGRATION_DIR)


def test_the_migration_entry_point_is_executable() -> None:
    """A non-executable apply.sh is sourced, not run, and set -eu then kills init."""
    import stat

    mode = (MIGRATION_DIR / "apply.sh").stat().st_mode
    assert mode & stat.S_IXUSR, oct(mode)


def test_the_deployment_environment_default_agrees_across_compose_and_example() -> None:
    """A .env.example copied onto prod must not silently tag events 'local'."""
    gateway_env = _services()["api_gateway"]["environment"]

    assert gateway_env["SSF_DEPLOYMENT_ENV"] == _env_example()["SSF_DEPLOYMENT_ENV"]


def test_the_local_stack_sends_the_probe_without_extra_configuration() -> None:
    """#199 is a discovery task: `docker compose up` must produce rows to inspect.

    A kill switch defaulting to off in the environment where discovery happens
    makes the deliverable invisible -- a reviewer sees an empty table.
    """
    gateway_env = _services()["api_gateway"]["environment"]
    example = _env_example()

    assert gateway_env["SSF_QUALITY_TELEMETRY_MODE"] == "probe"
    assert example["SSF_QUALITY_TELEMETRY_MODE"] == "probe"


def test_production_defines_the_collector_service() -> None:
    """Production has clickhouse but had no collector, so the probe could not run."""
    assert "otel-collector" in _production()


def test_the_production_collector_follows_production_conventions() -> None:
    """Digest-pinned and pre-loaded, like every other production service."""
    service = _production()["otel-collector"]

    assert "@sha256:" in service["image"], service["image"]
    assert service["restart"] == "unless-stopped"
    assert service["pull_policy"] == "never"


def test_the_production_collector_is_not_publicly_reachable() -> None:
    service = _production()["otel-collector"]

    assert service.get("ports") is None
    assert service.get("labels") is None
    assert sorted(str(port) for port in service["expose"]) == ["13133", "4318"]


def test_the_production_collector_mounts_its_config_read_only() -> None:
    """Paths in the production file are relative to deploy/production/."""
    volumes = _production()["otel-collector"]["volumes"]

    assert (
        "../../monitoring/otel-collector-config.yaml"
        ":/etc/otelcol-contrib/config.yaml:ro" in volumes
    ), volumes


def test_the_production_collector_waits_for_clickhouse() -> None:
    depends = _production()["otel-collector"]["depends_on"]

    assert depends["clickhouse"]["condition"] == "service_healthy"


def test_the_production_collector_has_clickhouse_credentials() -> None:
    env = _production_env("otel-collector")

    assert {"CLICKHOUSE_DB", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"} <= set(env)


def test_production_clickhouse_mounts_the_migrations() -> None:
    """Without this the schema is never applied on a rebuilt production volume."""
    volumes = _production()["clickhouse"]["volumes"]

    assert "../../deploy/clickhouse:/docker-entrypoint-initdb.d:ro" in volumes, volumes


def test_the_production_env_example_documents_every_required_variable() -> None:
    """`:?` variables missing from the example make it unusable as a template."""
    example = _production_env_example()

    for name in (
        "CLICKHOUSE_DB",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
        "SSF_QUALITY_TELEMETRY_MODE",
        "SSF_OTLP_LOGS_ENDPOINT",
        "SSF_RELEASE_VERSION",
        "SSF_DEPLOYMENT_ENV",
    ):
        assert name in example, name


def test_the_production_example_keeps_the_probe_off_until_chosen() -> None:
    assert _production_env_example()["SSF_QUALITY_TELEMETRY_MODE"] == "disabled"


def test_production_disables_the_probe_explicitly() -> None:
    """Turning telemetry on in production is a separate, deliberate decision.

    Relying on the code's fallback would mean a future default flip silently
    enables it there.
    """
    production = yaml.safe_load(
        (ROOT / "deploy" / "production" / "docker-compose.production.yml").read_text()
    )
    env = dict(
        entry.split("=", 1)
        for entry in production["services"]["api_gateway"]["environment"]
        if "=" in entry
    )

    # Production stays overridable -- that is what the kill switch is for. What
    # must hold is that the *default* is off.
    assert _interpolation_default(env["SSF_QUALITY_TELEMETRY_MODE"]) == "disabled"


def test_the_exporter_does_not_create_its_own_schema() -> None:
    """Lazy schema creation is what made the silver view un-appliable."""
    assert _collector_config()["exporters"]["clickhouse"]["create_schema"] is False


def test_no_processor_swallows_its_own_errors() -> None:
    """`ignore` lets a failed allowlist statement pass the record through intact."""
    for name, processor in _collector_config()["processors"].items():
        if "error_mode" in processor:
            assert processor["error_mode"] == "propagate", name


def test_non_quality_records_are_dropped_rather_than_rewritten() -> None:
    """Fail closed: the allowlist must not silently mangle a future customer."""
    config = _collector_config()
    conditions = config["processors"]["filter/quality_only"]["logs"]["log_record"]

    assert conditions == ['log.attributes["ssf.quality.event_id"] == nil']
    processors = config["service"]["pipelines"]["logs"]["processors"]
    assert processors.index("filter/quality_only") < processors.index("transform/allowlist")


def test_the_collector_allowlists_both_attribute_namespaces() -> None:
    """Contract test against the Python source of truth, not a hardcoded list."""
    statements = _collector_config()["processors"]["transform/allowlist"]["log_statements"][0][
        "statements"
    ]

    assert 'set(log.body, "")' in statements

    kept = {}
    for statement in statements:
        if not statement.startswith("keep_keys("):
            continue
        target, keys = statement[len("keep_keys(") : -1].split(",", 1)
        kept[target.strip()] = {
            part.strip().strip('"').strip("'")
            for part in keys.strip().lstrip("[").rstrip("]").split(",")
        }

    assert kept == {
        "log.attributes": set(ALLOWED_ATTRIBUTE_KEYS),
        "resource.attributes": ALLOWED_RESOURCE_KEYS,
    }


def test_the_view_reads_only_allowlisted_attribute_keys() -> None:
    """Third consumer of the same manifest: Python, collector, and the DDL."""
    view = (MIGRATIONS / "001_quality_events.sql").read_text()
    referenced = {
        line.split("LogAttributes['")[1].split("']")[0]
        for line in view.splitlines()
        if "LogAttributes['" in line
    }
    assert referenced <= set(ALLOWED_ATTRIBUTE_KEYS), referenced - set(ALLOWED_ATTRIBUTE_KEYS)


def test_collector_pipeline_has_no_extra_exporters() -> None:
    """Strictly additive: ClickHouse only. Prometheus and Loki are untouched."""
    config = _collector_config()
    assert config["service"]["pipelines"]["logs"]["exporters"] == ["clickhouse"]
    assert set(config["service"]["pipelines"]) == {"logs"}
