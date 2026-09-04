"""Static guards on the ClickHouse migrations, as the fourth allowlist consumer.

`test_otel_collector_compose_configuration.py` already proves the view reads
*only* allowlisted keys. That is one direction. The failure mode this file
exists for is the other one: a key opened in Python and in the collector but
never given a column, which makes the field vanish between the collector and
the table with no error anywhere in the pipeline.

These are text guards, not container guards, so they run in CI. The applied
behaviour (TTL actually set, inserts actually landing) is covered by
`tests/integration/test_quality_events_schema_apply.py`.
"""

import re
from pathlib import Path

import pytest

from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ATTRIBUTE_KEYS,
    AttributeKind,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "deploy" / "clickhouse" / "migrations"

SILVER = MIGRATIONS / "001_quality_events.sql"
GOLD = MIGRATIONS / "002_quality_events_fields_and_gold.sql"
MESSAGE = MIGRATIONS / "003_translation_message_fields.sql"
LIFECYCLE = MIGRATIONS / "004_session_lifecycle_fields.sql"

# The envelope keys 001 already projects; everything else must arrive in a later
# migration. Which one does not matter -- only that some migration gives the key
# a column and projects it -- so the per-key guard reads the tail of the series
# rather than one named file.
ENVELOPE_KEYS = {"ssf.quality.event_id", "ssf.quality.schema_version"}

# Everything after 001, discovered rather than listed: a migration added
# without being named here would otherwise be exempt from every guard below,
# which is the opposite of what this file is for.
FIELD_MIGRATIONS = tuple(
    path for path in sorted(MIGRATIONS.glob("*.sql")) if path.name[:3] > "001"
)


def _field_migration_sql() -> str:
    return "\n".join(path.read_text() for path in FIELD_MIGRATIONS)


def _sql() -> str:
    return "\n".join(path.read_text() for path in sorted(MIGRATIONS.glob("*.sql")))


def _projected_attribute_keys(sql: str) -> set[str]:
    return set(re.findall(r"LogAttributes\['([^']+)'\]", sql))


class TestEveryAllowlistedKeyReachesAColumn:
    def test_no_allowlisted_key_is_dropped_between_collector_and_table(self):
        missing = set(ALLOWED_ATTRIBUTE_KEYS) - _projected_attribute_keys(_sql())
        assert not missing, f"allowlisted but never projected into a column: {missing}"

    def test_the_migrations_project_nothing_outside_the_allowlist(self):
        extra = _projected_attribute_keys(_sql()) - set(ALLOWED_ATTRIBUTE_KEYS)
        assert not extra, f"projected but not allowlisted: {extra}"

    @pytest.mark.parametrize("key", sorted(set(ALLOWED_ATTRIBUTE_KEYS) - ENVELOPE_KEYS))
    def test_each_non_envelope_key_is_projected_by_a_field_migration(self, key):
        assert key in _projected_attribute_keys(_field_migration_sql())

    def test_the_latest_view_definition_projects_every_key(self):
        """MODIFY QUERY replaces the whole view, so only the last one counts.

        A migration that adds columns but re-states an older SELECT would drop
        the fields an earlier migration opened, with no error anywhere: the
        columns stay, and silently fill with their defaults.
        """
        latest = sorted(MIGRATIONS.glob("*.sql"))[-1].read_text()
        missing = set(ALLOWED_ATTRIBUTE_KEYS) - _projected_attribute_keys(latest)
        assert not missing, f"dropped by the newest MODIFY QUERY: {missing}"


class TestSilverGainsTypedColumns:
    def test_the_new_columns_are_added_rather_than_recreated(self):
        """Production's table already exists, so 002 must ALTER, never CREATE."""
        sql = GOLD.read_text()
        assert "ALTER TABLE quality_events" in sql
        assert "DROP TABLE quality_events" not in sql

    @pytest.mark.parametrize("migration", FIELD_MIGRATIONS, ids=lambda p: p.name)
    def test_adding_a_column_twice_is_safe(self, migration):
        adds = re.findall(r"ADD COLUMN(?! IF NOT EXISTS)", migration.read_text())
        assert not adds, "every ADD COLUMN must be IF NOT EXISTS; apply.sh re-runs"

    @pytest.mark.parametrize(
        "column",
        [
            "refiner_role",
            "model_ref",
            "refinement_outcome",
            "refinement_latency_ms",
            "refinement_changed",
            "source_lang",
            "target_lang",
            "error_code",
        ],
    )
    def test_the_silver_table_has_a_column_for_each_new_field(self, column):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{column}\b", GOLD.read_text())

    def test_numeric_projections_cannot_throw(self):
        """A view that throws fails the INSERT into otel_logs; the collector
        then retries that batch forever."""
        sql = _field_migration_sql()
        assert (
            "toUInt32OrZero(LogAttributes['ssf.quality.refinement_latency_ms'])" in sql
        )

    @pytest.mark.parametrize(
        "key",
        sorted(
            key
            for key, spec in ALLOWED_ATTRIBUTES.items()
            if spec.kind is AttributeKind.NUMBER and key != "ssf.quality.schema_version"
        ),
    )
    def test_every_numeric_key_is_projected_through_a_non_throwing_cast(self, key):
        """`toUInt32(x)` raises on a non-numeric string; `...OrZero` does not.

        The emitter's shape guard means a non-numeric value should be
        unreachable, but the view also sees whatever a rogue sender puts in
        bronze, and there the cost of a raising cast is an INSERT the collector
        retries forever.
        """
        assert f"toUInt32OrZero(LogAttributes['{key}'])" in _field_migration_sql()


def test_every_migration_after_the_first_is_covered_by_these_guards() -> None:
    """The discovery above is the guard's reach; assert it actually found them."""
    assert {path.name for path in FIELD_MIGRATIONS} == {
        GOLD.name,
        MESSAGE.name,
        LIFECYCLE.name,
    }


class TestTheOperatorDocsNameEveryMigration:
    """Enabling telemetry before a column migration is applied is unrepairable.

    The attributes are dropped at projection time and bronze expires after
    seven days, so a doc that under-states which migrations must be applied
    first costs data that cannot be recovered. `production.env.example` said
    "002 and 003" after 004 shipped.
    """

    OPERATOR_DOCS = (
        ROOT / "deploy" / "production" / "production.env.example",
        ROOT / "docs" / "operations" / "runbooks" / "clickhouse-operations.md",
    )

    @pytest.mark.parametrize("migration", FIELD_MIGRATIONS, ids=lambda path: path.name)
    @pytest.mark.parametrize("doc", OPERATOR_DOCS, ids=lambda path: path.name)
    def test_each_column_migration_is_named_where_operators_are_told_to_apply_it(
        self, doc, migration
    ):
        number = migration.name[:3]
        text = doc.read_text()
        applied = re.findall(
            r"migrations?\s+`?[0-9]{3}`?(?:[^.\n]*?`?[0-9]{3}`?)*", text
        )
        assert any(
            number in phrase for phrase in applied
        ), f"{doc.name} never lists migration {number} among those to apply"


class TestLifecycleColumns:
    @pytest.mark.parametrize(
        "column",
        [
            "lifecycle_phase",
            "termination_reason",
            "session_duration_ms",
            "message_count",
        ],
    )
    def test_the_silver_table_has_a_column_for_each_lifecycle_field(self, column):
        assert re.search(
            rf"ADD COLUMN IF NOT EXISTS\s+{column}\b", LIFECYCLE.read_text()
        )

    def test_the_lifecycle_migration_alters_rather_than_recreates(self):
        sql = LIFECYCLE.read_text()
        assert "ALTER TABLE quality_events" in sql
        assert "DROP TABLE" not in sql

    def test_the_raw_retention_is_left_alone(self):
        assert "MODIFY TTL" not in LIFECYCLE.read_text()


class TestMessageColumns:
    @pytest.mark.parametrize(
        "column",
        [
            "session_ref",
            "direction",
            "input_mode",
            "terminal_outcome",
            "failed_stage",
            "total_duration_ms",
            "asr_duration_ms",
            "translation_duration_ms",
            "refinement_duration_ms",
            "tts_duration_ms",
        ],
    )
    def test_the_silver_table_has_a_column_for_each_message_field(self, column):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{column}\b", MESSAGE.read_text())

    def test_the_session_reference_is_not_low_cardinality(self):
        """A keyed HMAC is as high-cardinality as the session count, and a
        LowCardinality dictionary that overflows costs more than it saves."""
        assert re.search(r"session_ref\s+String", MESSAGE.read_text())
        assert not re.search(r"session_ref\s+LowCardinality", MESSAGE.read_text())

    def test_the_message_migration_alters_rather_than_recreates(self):
        sql = MESSAGE.read_text()
        assert "ALTER TABLE quality_events" in sql
        assert "DROP TABLE" not in sql

    def test_the_raw_retention_is_left_alone(self):
        assert "MODIFY TTL" not in MESSAGE.read_text()


class TestGoldTier:
    def test_the_gold_table_exists(self):
        assert "CREATE TABLE IF NOT EXISTS quality_events_daily" in GOLD.read_text()

    def test_the_gold_tier_expires_after_thirteen_months(self):
        assert re.search(
            r"TTL\s+event_date\s*\+\s*INTERVAL\s+13\s+MONTH", GOLD.read_text()
        )

    def test_the_raw_tier_keeps_its_thirty_day_retention(self):
        """002 must not silently change what 001 fixed at table creation."""
        assert re.search(r"INTERVAL\s+30\s+DAY", SILVER.read_text())
        assert "MODIFY TTL" not in GOLD.read_text()

    def test_the_gold_tier_aggregates_rather_than_stores_rows(self):
        assert "AggregatingMergeTree" in GOLD.read_text()

    def test_counting_is_idempotent_under_duplicate_delivery(self):
        """A retried export inserts the bronze row twice, and the silver
        ReplacingMergeTree only collapses it at merge time -- so the gold tier
        must count distinct event_ids, not rows, or a retry inflates it."""
        sql = GOLD.read_text()
        assert "uniqExactState(event_id)" in sql
        assert "uniqExactStateIf(event_id, refinement_changed = 1)" in sql
        # A sumState-based counter reported 2 for one duplicated event while
        # uniqExact reported 1; no plain counter may return.
        assert "countState()" not in sql
        assert "sumState(" not in sql

    def test_the_gold_view_is_fed_from_silver(self):
        assert re.search(
            r"CREATE MATERIALIZED VIEW IF NOT EXISTS quality_events_daily_mv\s+TO\s+quality_events_daily",
            GOLD.read_text(),
        )


class TestMigrationIsIdempotent:
    def test_every_create_is_guarded(self):
        unguarded = re.findall(
            r"CREATE (?:TABLE|MATERIALIZED VIEW)(?! IF NOT EXISTS)", GOLD.read_text()
        )
        assert not unguarded

    def test_the_silver_view_is_modified_in_place_not_dropped(self):
        """DROP VIEW leaves a window where inserts are not projected at all."""
        sql = GOLD.read_text()
        assert "ALTER TABLE quality_events_mv MODIFY QUERY" in sql
        assert "DROP VIEW" not in sql
