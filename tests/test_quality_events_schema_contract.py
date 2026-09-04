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

from services.api_gateway.quality_telemetry import ALLOWED_ATTRIBUTE_KEYS

MIGRATIONS = Path(__file__).resolve().parents[1] / "deploy" / "clickhouse" / "migrations"

SILVER = MIGRATIONS / "001_quality_events.sql"
GOLD = MIGRATIONS / "002_quality_events_fields_and_gold.sql"

# The envelope keys 001 already projects; everything else must arrive in 002.
ENVELOPE_KEYS = {"ssf.quality.event_id", "ssf.quality.schema_version"}


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
    def test_each_non_envelope_key_is_projected_by_the_second_migration(self, key):
        assert key in _projected_attribute_keys(GOLD.read_text())


class TestSilverGainsTypedColumns:
    def test_the_new_columns_are_added_rather_than_recreated(self):
        """Production's table already exists, so 002 must ALTER, never CREATE."""
        sql = GOLD.read_text()
        assert "ALTER TABLE quality_events" in sql
        assert "DROP TABLE quality_events" not in sql

    def test_adding_a_column_twice_is_safe(self):
        adds = re.findall(r"ADD COLUMN(?! IF NOT EXISTS)", GOLD.read_text())
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
        sql = GOLD.read_text()
        assert "toUInt32OrZero(LogAttributes['ssf.quality.refinement_latency_ms'])" in sql


class TestGoldTier:
    def test_the_gold_table_exists(self):
        assert "CREATE TABLE IF NOT EXISTS quality_events_daily" in GOLD.read_text()

    def test_the_gold_tier_expires_after_thirteen_months(self):
        assert re.search(r"TTL\s+event_date\s*\+\s*INTERVAL\s+13\s+MONTH", GOLD.read_text())

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
