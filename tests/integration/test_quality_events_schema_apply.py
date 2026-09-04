"""Applies deploy/clickhouse/ to a scratch database and asserts what it does.

Requires a running clickhouse. These replace text assertions about the DDL: a
grep for "ReplacingMergeTree" proves the file says it, not that a duplicate
collapses or that a malformed id is kept out.
"""

import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
MIGRATIONS = sorted((ROOT / "deploy" / "clickhouse" / "migrations").glob("*.sql"))
SCRATCH_DB = "ssf_schema_apply_test"

# Every object the repository's migrations own, in ORDER BY name order.
EXPECTED_TABLES = [
    "otel_logs",
    "quality_events",
    "quality_events_daily",
    "quality_events_daily_mv",
    "quality_events_mv",
]

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
    assert tables == EXPECTED_TABLES


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
        f"SELECT count() FROM quality_events FINAL "
        f"WHERE event_id = toUUID('{event_id}')",
        database=scratch_db,
    )
    assert count == "1"


def test_every_tier_expires_on_its_documented_retention(scratch_db: str) -> None:
    """7 days bronze, 30 days silver, 13 months gold. ClickHouse fixes TTL at
    creation, so a tier that ships without one can never be given one."""
    ddl = {
        table: _client(f"SHOW CREATE TABLE {table}", database=scratch_db)
        for table in ("otel_logs", "quality_events", "quality_events_daily")
    }
    assert "toIntervalDay(7)" in ddl["otel_logs"], ddl["otel_logs"]
    assert "toIntervalDay(30)" in ddl["quality_events"], ddl["quality_events"]
    assert "toIntervalMonth(13)" in ddl["quality_events_daily"], ddl[
        "quality_events_daily"
    ]


# Whole segments, not substrings: "error" also matches `error_code`, a closed
# enum from the taxonomy, and "ip" matches "pipeline". The value-level guarantee
# lives in the attribute manifest, which declares a shape for every key and has
# no free-text kind; this stays a naming tripwire on top of it.
_CONTENT_COLUMN = re.compile(
    r"(?:^|_)(?:body|text|transcript|message|detail|payload|url|uri|ip|prompt)(?:_|$)"
)

# A numeric or date column cannot hold a sentence whatever it is called, so the
# name tripwire applies to the string-typed ones. `message_count` is a UInt32.
_STRING_TYPE = re.compile(r"String|FixedString|Enum")


def _silver_columns(db: str) -> list[tuple[str, str]]:
    rows = _client(
        "SELECT lower(name), type FROM system.columns "
        "WHERE database = currentDatabase() AND table = 'quality_events'",
        database=db,
    ).splitlines()
    return [tuple(row.split("\t")) for row in rows]


def test_the_runbooks_column_count_matches_the_applied_schema(scratch_db: str) -> None:
    """Step 11 tells an operator to compare a number against production.

    The number was wrong once -- counted by hand off a column listing, missing
    `ingested_at_utc` -- which would have had an operator re-run `apply.sh`
    against a correctly migrated database and conclude nothing had happened.
    """
    runbook = (
        ROOT / "docs" / "operations" / "runbooks" / "clickhouse-operations.md"
    ).read_text()
    documented = re.search(r"Expect `(\d+)`\. Fewer means a migration", runbook)
    assert documented, "step 11 no longer states an expected column count"

    actual = _client(
        "SELECT count() FROM system.columns WHERE database = currentDatabase() "
        "AND table = 'quality_events'",
        database=scratch_db,
    )
    assert actual == documented.group(1), (actual, documented.group(1))


def test_silver_stores_no_content_column(scratch_db: str) -> None:
    """Checks the live table, so the materialized view cannot smuggle one in."""
    columns = _silver_columns(scratch_db)
    assert columns, "quality_events reported no columns"

    offenders = [
        (name, type_)
        for name, type_ in columns
        if _STRING_TYPE.search(type_) and _CONTENT_COLUMN.search(name)
    ]
    assert not offenders, offenders


def test_any_content_named_column_is_typed_so_it_cannot_hold_content(
    scratch_db: str,
) -> None:
    """The other half: `message_count` reads like content and is a UInt32.

    That exemption is only sound because of the type, so assert the type rather
    than assuming it -- widening the column to String must fail here.
    """
    for name, type_ in _silver_columns(scratch_db):
        if not _CONTENT_COLUMN.search(name):
            continue
        assert not _STRING_TYPE.search(type_), (name, type_)


def _insert_refinement(
    db: str, event_id: str, *, latency_ms: str, changed: str
) -> None:
    _client(
        f"INSERT INTO otel_logs ({', '.join(_EXPORTER_COLUMNS)}) VALUES "
        f"(now64(9), '', '', 0, '', 0, 'api_gateway', '', '', "
        f"{{'service.version': 'itest', 'deployment.environment.name': 'itest'}}, "
        f"'', 'ssf.quality', '', {{}}, "
        f"{{'ssf.quality.event_id': '{event_id}', 'ssf.quality.schema_version': '1', "
        f"'ssf.quality.refiner_role': 'candidate', 'ssf.quality.model_ref': 'phi4-mini', "
        f"'ssf.quality.refinement_outcome': 'success', "
        f"'ssf.quality.refinement_latency_ms': '{latency_ms}', "
        f"'ssf.quality.refinement_changed': '{changed}', "
        f"'ssf.quality.source_lang': 'en', 'ssf.quality.target_lang': 'de', "
        f"'ssf.quality.error_code': 'none'}}, 'refinement_attempt')",
        database=db,
    )


def test_the_silver_view_projects_every_typed_field(scratch_db: str) -> None:
    event_id = str(uuid.uuid4())
    _insert_refinement(scratch_db, event_id, latency_ms="340", changed="true")

    row = _client(
        "SELECT refiner_role, model_ref, refinement_outcome, refinement_latency_ms, "
        f"refinement_changed, source_lang, target_lang, error_code FROM quality_events "
        f"FINAL WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == [
        "candidate",
        "phi4-mini",
        "success",
        "340",
        "1",
        "en",
        "de",
        "none",
    ]


def _insert_message(db: str, event_id: str, **overrides: str) -> None:
    attributes = {
        "ssf.quality.event_id": event_id,
        "ssf.quality.schema_version": "1",
        "ssf.quality.session_ref": "a" * 32,
        "ssf.quality.direction": "customer_to_admin",
        "ssf.quality.input_mode": "audio",
        "ssf.quality.source_lang": "de",
        "ssf.quality.target_lang": "en",
        "ssf.quality.terminal_outcome": "failure",
        "ssf.quality.failed_stage": "tts",
        "ssf.quality.error_code": "upstream_timeout",
        "ssf.quality.total_duration_ms": "2500",
        "ssf.quality.asr_duration_ms": "910",
        "ssf.quality.translation_duration_ms": "420",
        "ssf.quality.refinement_duration_ms": "300",
        "ssf.quality.tts_duration_ms": "830",
    }
    attributes.update(overrides)
    pairs = ", ".join(f"'{k}': '{v}'" for k, v in attributes.items())
    _client(
        f"INSERT INTO otel_logs ({', '.join(_EXPORTER_COLUMNS)}) VALUES "
        f"(now64(9), '', '', 0, '', 0, 'api_gateway', '', '', "
        f"{{'service.version': 'itest', 'deployment.environment.name': 'itest'}}, "
        f"'', 'ssf.quality', '', {{}}, {{{pairs}}}, 'translation_message')",
        database=db,
    )


def test_the_silver_view_projects_every_message_field(scratch_db: str) -> None:
    event_id = str(uuid.uuid4())
    _insert_message(scratch_db, event_id)

    row = _client(
        "SELECT session_ref, direction, input_mode, terminal_outcome, failed_stage, "
        "source_lang, target_lang, error_code, total_duration_ms, asr_duration_ms, "
        "translation_duration_ms, refinement_duration_ms, tts_duration_ms "
        f"FROM quality_events FINAL WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == [
        "a" * 32,
        "customer_to_admin",
        "audio",
        "failure",
        "tts",
        "de",
        "en",
        "upstream_timeout",
        "2500",
        "910",
        "420",
        "300",
        "830",
    ]


def test_a_refinement_row_still_projects_after_the_message_migration(
    scratch_db: str,
) -> None:
    """003 replaces the whole view definition, so 002's fields must survive it.

    A MODIFY QUERY that re-stated an older SELECT would leave the columns in
    place and silently fill them with defaults -- no error, no missing column,
    just zeros where the refinement latencies used to be.
    """
    event_id = str(uuid.uuid4())
    _insert_refinement(scratch_db, event_id, latency_ms="777", changed="true")

    row = _client(
        "SELECT refiner_role, refinement_latency_ms FROM quality_events FINAL "
        f"WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == ["candidate", "777"]


def test_a_message_row_leaves_the_refinement_columns_at_their_defaults(
    scratch_db: str,
) -> None:
    """Map access on an absent key yields the type default rather than raising.

    A view that throws fails the originating INSERT into otel_logs, which the
    collector then retries forever.
    """
    event_id = str(uuid.uuid4())
    _insert_message(scratch_db, event_id)

    # Compared in SQL rather than in Python: an empty leading column would be
    # stripped out of the client's stdout and the assertion would pass on a
    # shorter row than it thinks it is reading.
    row = _client(
        "SELECT empty(refiner_role), empty(model_ref), refinement_latency_ms, "
        f"refinement_changed FROM quality_events FINAL WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == ["1", "1", "0", "0"]


def test_a_non_numeric_duration_from_a_rogue_sender_becomes_zero(
    scratch_db: str,
) -> None:
    """The emitter's shape guard makes this unreachable through the gateway.

    Bronze also takes whatever a sender on the compose network writes, and
    there a raising cast would fail the INSERT the collector retries forever.
    """
    event_id = str(uuid.uuid4())
    _insert_message(scratch_db, event_id, **{"ssf.quality.tts_duration_ms": "soon"})

    row = _client(
        f"SELECT tts_duration_ms FROM quality_events FINAL WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row == "0"


def _insert_lifecycle(db: str, event_id: str, **overrides: str) -> None:
    attributes = {
        "ssf.quality.event_id": event_id,
        "ssf.quality.schema_version": "1",
        "ssf.quality.session_ref": "c" * 32,
        "ssf.quality.lifecycle_phase": "terminated",
        "ssf.quality.termination_reason": "session_timeout",
        "ssf.quality.session_duration_ms": "1800000",
        "ssf.quality.message_count": "12",
    }
    attributes.update(overrides)
    pairs = ", ".join(f"'{k}': '{v}'" for k, v in attributes.items())
    _client(
        f"INSERT INTO otel_logs ({', '.join(_EXPORTER_COLUMNS)}) VALUES "
        f"(now64(9), '', '', 0, '', 0, 'api_gateway', '', '', "
        f"{{'service.version': 'itest', 'deployment.environment.name': 'itest'}}, "
        f"'', 'ssf.quality', '', {{}}, {{{pairs}}}, 'session_lifecycle')",
        database=db,
    )


def test_the_silver_view_projects_every_lifecycle_field(scratch_db: str) -> None:
    event_id = str(uuid.uuid4())
    _insert_lifecycle(scratch_db, event_id)

    row = _client(
        "SELECT session_ref, lifecycle_phase, termination_reason, "
        f"session_duration_ms, message_count FROM quality_events FINAL "
        f"WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == [
        "c" * 32,
        "terminated",
        "session_timeout",
        "1800000",
        "12",
    ]


def test_a_message_row_still_projects_after_the_lifecycle_migration(
    scratch_db: str,
) -> None:
    """004 replaces the whole view definition, so 003's fields must survive it.

    Same failure mode as 003 over 002: the columns stay and silently fill with
    defaults, with no error and no missing column.
    """
    event_id = str(uuid.uuid4())
    _insert_message(scratch_db, event_id)

    row = _client(
        "SELECT input_mode, tts_duration_ms FROM quality_events FINAL "
        f"WHERE event_id = '{event_id}'",
        database=scratch_db,
    )
    assert row.split("\t") == ["audio", "830"]


def test_a_session_can_be_joined_to_the_messages_it_carried(scratch_db: str) -> None:
    """The reason both events derive `session_ref` the same way.

    "Messages per session" and "sessions that carried none" are the ratios this
    event exists for, and neither is computable if the two references disagree.
    """
    reference = "d" * 32
    _insert_lifecycle(
        scratch_db,
        str(uuid.uuid4()),
        **{"ssf.quality.session_ref": reference, "ssf.quality.message_count": "2"},
    )
    for _ in range(2):
        _insert_message(
            scratch_db,
            str(uuid.uuid4()),
            **{"ssf.quality.session_ref": reference},
        )

    joined = _client(
        "SELECT countIf(event_type = 'translation_message'), "
        "maxIf(message_count, event_type = 'session_lifecycle') "
        f"FROM quality_events FINAL WHERE session_ref = '{reference}'",
        database=scratch_db,
    )
    assert joined.split("\t") == ["2", "2"]


def test_the_production_upgrade_path_adds_the_message_columns() -> None:
    """Production already holds 001 and 002 with data; 003 arrives on top.

    initdb does not re-run on a volume that has data, so this is the only path
    a deployed stack takes -- and the one a fresh-database test never exercises.
    """
    upgrade_db = f"{SCRATCH_DB}_upgrade"
    _client(f"DROP DATABASE IF EXISTS {upgrade_db}; CREATE DATABASE {upgrade_db};")
    try:
        for path in MIGRATIONS:
            if path.name[:3] > "002":
                continue
            _client(path.read_text(), database=upgrade_db)

        before = str(uuid.uuid4())
        _insert_refinement(upgrade_db, before, latency_ms="120", changed="false")

        for path in MIGRATIONS:
            _client(path.read_text(), database=upgrade_db)

        after = str(uuid.uuid4())
        _insert_message(upgrade_db, after)
        lifecycle = str(uuid.uuid4())
        _insert_lifecycle(upgrade_db, lifecycle)

        assert (
            _client(
                "SELECT refinement_latency_ms FROM quality_events FINAL "
                f"WHERE event_id = '{before}'",
                database=upgrade_db,
            )
            == "120"
        ), "a row written before the migration must survive it"
        assert (
            _client(
                f"SELECT input_mode FROM quality_events FINAL WHERE event_id = '{after}'",
                database=upgrade_db,
            )
            == "audio"
        )
        assert (
            _client(
                "SELECT lifecycle_phase FROM quality_events FINAL "
                f"WHERE event_id = '{lifecycle}'",
                database=upgrade_db,
            )
            == "terminated"
        )
    finally:
        _client(f"DROP DATABASE IF EXISTS {upgrade_db};")


def test_a_gold_count_is_not_inflated_by_a_duplicated_delivery(scratch_db: str) -> None:
    """Task 4.4, aggregate correctness.

    The retry path delivers the same event_id twice and silver's
    ReplacingMergeTree only collapses that at merge time, so a plain counter in
    gold would over-report permanently -- an aggregate cannot be un-counted.
    A sumState-based `changed_events` was observed reporting 2 for one event.
    """
    event_id = str(uuid.uuid4())
    for _ in range(2):
        _insert_refinement(scratch_db, event_id, latency_ms="500", changed="true")

    counts = _client(
        "SELECT uniqExactMerge(events), uniqExactMerge(changed_events) "
        "FROM quality_events_daily WHERE model_ref = 'phi4-mini'",
        database=scratch_db,
    )
    events, changed = counts.split("\t")
    duplicates = _client(
        f"SELECT count() FROM otel_logs WHERE LogAttributes['ssf.quality.event_id'] = '{event_id}'",
        database=scratch_db,
    )

    assert duplicates == "2", "the duplicate delivery must actually have landed"
    assert int(events) == int(changed), (events, changed)


def test_gold_totals_agree_with_the_silver_rows_they_summarise(scratch_db: str) -> None:
    gold = _client(
        "SELECT uniqExactMerge(events) FROM quality_events_daily "
        "WHERE event_type = 'refinement_attempt'",
        database=scratch_db,
    )
    silver = _client(
        "SELECT uniqExact(event_id) FROM quality_events FINAL "
        "WHERE event_type = 'refinement_attempt'",
        database=scratch_db,
    )
    assert gold == silver, (gold, silver)


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
        tables = _await_tables(container, EXPECTED_TABLES)
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], capture_output=True, check=False
        )

    assert tables == EXPECTED_TABLES, tables


def _clickhouse_image() -> str:
    compose = (ROOT / "docker-compose.yml").read_text()
    for line in compose.splitlines():
        if "clickhouse/clickhouse-server:" in line:
            return line.split("image:")[1].strip()
    raise AssertionError("clickhouse image not found in docker-compose.yml")


def _await_tables(container: str, expected: list[str]) -> list[str]:
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
        names = sorted(completed.stdout.split())
        if names == expected:
            return names
        time.sleep(2)
    pytest.fail(
        f"fresh container never created the tables: {completed.stdout!r} {completed.stderr!r}"
    )
