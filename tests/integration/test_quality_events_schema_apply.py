"""Applies deploy/clickhouse/ to a scratch database and asserts what it does.

Requires a running clickhouse. These replace text assertions about the DDL: a
grep for "ReplacingMergeTree" proves the file says it, not that a duplicate
collapses or that a malformed id is kept out.
"""

import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
MIGRATIONS = sorted((ROOT / "deploy" / "clickhouse" / "migrations").glob("*.sql"))
SCRATCH_DB = "ssf_schema_apply_test"

# Exactly the columns the ClickHouse exporter names in its INSERT. Bronze must
# accept all of them or every export fails.
_EXPORTER_COLUMNS = (
    "Timestamp",
    "TraceId",
    "SpanId",
    "TraceFlags",
    "SeverityText",
    "SeverityNumber",
    "ServiceName",
    "Body",
    "ResourceSchemaUrl",
    "ResourceAttributes",
    "ScopeSchemaUrl",
    "ScopeName",
    "ScopeVersion",
    "ScopeAttributes",
    "LogAttributes",
    "EventName",
)


def _client(sql: str, database: str | None = None) -> str:
    """clickhouse-client inside the container, with credentials from its env."""
    db = f'--database "{database}" ' if database else ""
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "clickhouse",
            "sh",
            "-ec",
            f'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" '
            f"{db}--multiquery",
        ],
        input=sql,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def scratch_db() -> str:
    _client(f"DROP DATABASE IF EXISTS {SCRATCH_DB}; CREATE DATABASE {SCRATCH_DB};")
    for path in MIGRATIONS:
        _client(path.read_text(), database=SCRATCH_DB)
    yield SCRATCH_DB
    _client(f"DROP DATABASE IF EXISTS {SCRATCH_DB};")


def _insert_bronze(db: str, event_id: str, *, schema_version: str = "1") -> None:
    _client(
        f"INSERT INTO otel_logs ({', '.join(_EXPORTER_COLUMNS)}) VALUES "
        f"(now64(9), '', '', 0, '', 0, 'api_gateway', '', '', "
        f"{{'service.version': 'itest', 'deployment.environment.name': 'itest'}}, "
        f"'', 'ssf.quality', '', {{}}, "
        f"{{'ssf.quality.event_id': '{event_id}', "
        f"'ssf.quality.schema_version': '{schema_version}'}}, 'telemetry_probe')",
        database=db,
    )


def test_the_migrations_apply_to_an_empty_database(scratch_db: str) -> None:
    """Bronze must not be a lazily-created dependency: fresh deploys need both."""
    tables = _client(
        "SELECT name FROM system.tables WHERE database = currentDatabase() ORDER BY name",
        database=scratch_db,
    ).splitlines()
    assert tables == ["otel_logs", "quality_events", "quality_events_mv"]


def test_bronze_accepts_every_column_the_exporter_inserts(scratch_db: str) -> None:
    columns = set(
        _client(
            "SELECT name FROM system.columns WHERE database = currentDatabase() "
            "AND table = 'otel_logs'",
            database=scratch_db,
        ).splitlines()
    )
    assert set(_EXPORTER_COLUMNS) <= columns, set(_EXPORTER_COLUMNS) - columns


def test_a_well_formed_event_is_projected_into_silver(scratch_db: str) -> None:
    event_id = str(uuid.uuid4())
    _insert_bronze(scratch_db, event_id)

    row = _client(
        f"SELECT event_type, service_name, service_version, deployment_env, "
        f"schema_version FROM quality_events FINAL "
        f"WHERE event_id = toUUID('{event_id}')",
        database=scratch_db,
    )
    assert row.split("\t") == ["telemetry_probe", "api_gateway", "itest", "itest", "1"]


def test_a_malformed_event_id_is_kept_out_of_silver(scratch_db: str) -> None:
    """toUUIDOrZero would collapse every malformed event onto one nil-UUID row."""
    _insert_bronze(scratch_db, "not-a-uuid")

    nil_rows = _client(
        "SELECT count() FROM quality_events "
        "WHERE event_id = toUUID('00000000-0000-0000-0000-000000000000')",
        database=scratch_db,
    )
    assert nil_rows == "0"


def test_an_empty_event_id_is_kept_out_of_silver(scratch_db: str) -> None:
    _insert_bronze(scratch_db, "")

    nil_rows = _client(
        "SELECT count() FROM quality_events "
        "WHERE event_id = toUUID('00000000-0000-0000-0000-000000000000')",
        database=scratch_db,
    )
    assert nil_rows == "0"


def test_a_duplicated_delivery_collapses_to_one_silver_row(scratch_db: str) -> None:
    event_id = str(uuid.uuid4())
    _insert_bronze(scratch_db, event_id)
    _insert_bronze(scratch_db, event_id)

    count = _client(
        f"SELECT count() FROM quality_events FINAL " f"WHERE event_id = toUUID('{event_id}')",
        database=scratch_db,
    )
    assert count == "1"


def test_both_tiers_expire_on_their_documented_retention(scratch_db: str) -> None:
    """7 days bronze, 30 days silver. A missing TTL grows the disk forever."""
    ddl = {
        table: _client(f"SHOW CREATE TABLE {table}", database=scratch_db)
        for table in ("otel_logs", "quality_events")
    }
    assert "toIntervalDay(7)" in ddl["otel_logs"], ddl["otel_logs"]
    assert "toIntervalDay(30)" in ddl["quality_events"], ddl["quality_events"]


def test_silver_stores_no_content_column(scratch_db: str) -> None:
    """Checks the live table, so the materialized view cannot smuggle one in."""
    columns = _client(
        "SELECT lower(name) FROM system.columns WHERE database = currentDatabase() "
        "AND table = 'quality_events'",
        database=scratch_db,
    ).splitlines()
    forbidden = ("body", "text", "audio", "transcript", "error", "ip", "session")
    assert not [c for c in columns if any(f in c for f in forbidden)], columns


def test_a_fresh_volume_gets_both_tiers_in_the_configured_database() -> None:
    """The deploy path, on a throwaway container with an empty data directory.

    The image's entrypoint runs bare *.sql files through a client with no
    --database flag, so migrations placed directly in the initdb directory land
    in `default` while the collector writes to $CLICKHOUSE_DB -- tables present,
    exports failing. This asserts the database they actually land in.
    """
    container = "ssf-freshdeploy-pytest"
    subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "-e",
            "CLICKHOUSE_DB=ssf_analytics",
            "-e",
            "CLICKHOUSE_USER=ssf_telemetry",
            "-e",
            "CLICKHOUSE_PASSWORD=freshtest",
            "-v",
            f"{ROOT / 'deploy' / 'clickhouse'}:/docker-entrypoint-initdb.d:ro",
            _clickhouse_image(),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        tables = _await_tables(container)
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)

    assert tables == ["otel_logs", "quality_events", "quality_events_mv"], tables


def _clickhouse_image() -> str:
    compose = (ROOT / "docker-compose.yml").read_text()
    for line in compose.splitlines():
        if "clickhouse/clickhouse-server:" in line:
            return line.split("image:")[1].strip()
    raise AssertionError("clickhouse image not found in docker-compose.yml")


def _await_tables(container: str) -> list[str]:
    """Poll past the entrypoint's temporary init server to the real one."""
    query = [
        "docker",
        "exec",
        container,
        "clickhouse-client",
        "--user",
        "ssf_telemetry",
        "--password",
        "freshtest",
        "--query",
        "SELECT name FROM system.tables WHERE database = 'ssf_analytics' ORDER BY name",
    ]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        completed = subprocess.run(query, capture_output=True, text=True)
        names = completed.stdout.split()
        if len(names) == 3:
            return sorted(names)
        time.sleep(2)
    pytest.fail(
        f"fresh container never created the tables: {completed.stdout!r} {completed.stderr!r}"
    )
