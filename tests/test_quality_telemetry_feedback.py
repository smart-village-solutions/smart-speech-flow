"""The `feedback_submitted` event: ratings in ClickHouse, text nowhere near it.

The submission is split across two stores. This event is the analytical half:
ratings, NPS and two opaque references. Its whole reason for existing is that
the other half -- the free text -- cannot be represented here at all, which is
enforced by AttributeKind having no free-text member.

`emit_feedback_submitted` takes `event_id` from its caller rather than minting
one, unlike every sibling. #305's reconciler re-emits a failed delivery with
the same id, and silver's ReplacingMergeTree plus gold's uniqExactState only
deduplicate if that id is stable.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTE_KEYS,
    ALLOWED_ATTRIBUTES,
    AttributeKind,
    FeedbackSubmittedEvent,
    ProbeOutcome,
    QualityEventType,
    QualityTelemetry,
    TelemetryMode,
    discard_event,
    to_otlp_attributes,
)
from services.api_gateway.session_pseudonym import MISSING_TENANT_REFERENCE

ROOT = Path(__file__).parents[1]
SESSION_REFERENCE = "c" * 32
FEEDBACK_REFERENCE = "d" * 32
TENANT_REFERENCE = "e" * 12

NEW_KEYS = {
    "ssf.quality.feedback_ref": AttributeKind.OPAQUE_REF,
    "ssf.quality.translation_quality": AttributeKind.NUMBER,
    "ssf.quality.performance": AttributeKind.NUMBER,
    "ssf.quality.usability": AttributeKind.NUMBER,
    "ssf.quality.net_promoter_score": AttributeKind.NUMBER,
    "ssf.quality.feedback_form_version": AttributeKind.LABEL,
}


def _event(**overrides) -> FeedbackSubmittedEvent:
    fields = dict(
        event_id=uuid4(),
        schema_version=1,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type=QualityEventType.FEEDBACK_SUBMITTED,
        session_ref=SESSION_REFERENCE,
        feedback_ref=FEEDBACK_REFERENCE,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        feedback_form_version="v1",
    )
    fields.update(overrides)
    return FeedbackSubmittedEvent(**fields)


class _Recording:
    def __init__(self):
        self.calls = []

    def __call__(self, name, attributes, emitted_at_utc):
        self.calls.append((name, dict(attributes), emitted_at_utc))


def _telemetry(mode=TelemetryMode.ENABLED, exporter=None):
    return QualityTelemetry(
        mode=mode, exporter=exporter or discard_event, registry=CollectorRegistry()
    )


def _emit(telemetry, **overrides):
    fields = dict(
        event_id=uuid4(),
        session_ref=SESSION_REFERENCE,
        feedback_ref=FEEDBACK_REFERENCE,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        form_version="v1",
    )
    fields.update(overrides)
    return telemetry.emit_feedback_submitted(**fields)


class TestTheEventCarriesNoContent:
    def test_every_attribute_is_a_number_an_enum_a_label_or_a_reference(self):
        kinds = {ALLOWED_ATTRIBUTES[key].kind for key in to_otlp_attributes(_event())}

        assert kinds <= {
            AttributeKind.UUID,
            AttributeKind.NUMBER,
            AttributeKind.ENUM,
            AttributeKind.LABEL,
            AttributeKind.OPAQUE_REF,
            AttributeKind.TENANT_REF,
        }

    def test_no_attribute_could_hold_a_sentence(self):
        """A LABEL rejects whitespace, so no field can carry free text."""
        label = re.compile(r"\A[A-Za-z0-9._:+/-]{1,64}\Z", re.ASCII)

        assert not label.match("the translation was wrong")

    def test_the_form_version_is_a_label_not_free_text(self):
        assert ALLOWED_ATTRIBUTES["ssf.quality.feedback_form_version"].kind is AttributeKind.LABEL

    def test_it_emits_no_key_outside_the_allowlist(self):
        assert set(to_otlp_attributes(_event())) <= ALLOWED_ATTRIBUTE_KEYS


class TestTheAllowlistKnowsTheNewFields:
    @pytest.mark.parametrize("key,kind", sorted(NEW_KEYS.items()))
    def test_the_key_is_allowlisted_with_the_declared_kind(self, key, kind):
        assert ALLOWED_ATTRIBUTES[key].kind is kind


class TestInvariants:
    @pytest.mark.parametrize("field", ["translation_quality", "performance", "usability"])
    @pytest.mark.parametrize("value", [0, 6, -1])
    def test_ratings_outside_one_to_five_are_rejected(self, field, value):
        with pytest.raises(ValueError):
            _event(**{field: value})

    @pytest.mark.parametrize("value", [-1, 11])
    def test_an_nps_outside_zero_to_ten_is_rejected(self, value):
        with pytest.raises(ValueError):
            _event(net_promoter_score=value)

    @pytest.mark.parametrize("value", [0, 10])
    def test_the_nps_boundaries_are_accepted(self, value):
        assert _event(net_promoter_score=value)

    def test_a_session_reference_of_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            _event(session_ref="ABC123")

    def test_a_feedback_reference_of_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            _event(feedback_ref="not-a-reference")

    def test_the_wrong_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            _event(event_type=QualityEventType.SESSION_LIFECYCLE)


class TestEmission:
    def test_it_emits_the_event_id_the_caller_supplied(self):
        """The reconciler re-emits this id; minting a fresh one double-counts."""
        recording = _Recording()
        telemetry = _telemetry(exporter=recording)
        event_id = uuid4()

        result = _emit(telemetry, event_id=event_id)

        assert result.outcome is ProbeOutcome.EMITTED
        assert result.event_id == event_id
        assert recording.calls[0][1]["ssf.quality.event_id"] == str(event_id)

    def test_re_emitting_the_same_id_produces_an_identical_event_id(self):
        recording = _Recording()
        telemetry = _telemetry(exporter=recording)
        event_id = uuid4()

        _emit(telemetry, event_id=event_id)
        _emit(telemetry, event_id=event_id)

        first, second = recording.calls
        assert first[1]["ssf.quality.event_id"] == second[1]["ssf.quality.event_id"]

    def test_it_emits_under_the_feedback_event_name(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording))

        assert recording.calls[0][0] == "feedback_submitted"

    def test_the_ratings_reach_the_exporter(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), translation_quality=2, usability=1)

        attributes = recording.calls[0][1]
        assert attributes["ssf.quality.translation_quality"] == "2"
        assert attributes["ssf.quality.usability"] == "1"
        assert attributes["ssf.quality.net_promoter_score"] == "9"

    def test_both_references_reach_the_exporter(self):
        """Without both, the row cannot be joined to anything."""
        recording = _Recording()

        _emit(_telemetry(exporter=recording))

        attributes = recording.calls[0][1]
        assert attributes["ssf.quality.session_ref"] == SESSION_REFERENCE
        assert attributes["ssf.quality.feedback_ref"] == FEEDBACK_REFERENCE

    def test_a_disabled_deployment_emits_nothing(self):
        recording = _Recording()

        result = _emit(_telemetry(mode=TelemetryMode.DISABLED, exporter=recording))

        assert result.outcome is ProbeOutcome.DISABLED
        assert recording.calls == []

    def test_an_out_of_range_rating_is_dropped_rather_than_raised(self):
        """Telemetry must never fail the request that produced it."""
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), translation_quality=99)

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []

    def test_a_malformed_form_version_is_coerced_not_dropped(self):
        """Coerce rather than trust, matching the sibling emitters.

        A form version that fails the LABEL shape is operator misconfiguration,
        but the ratings alongside it are still valid data. Dropping the event
        would lose them to protect a field that has a safe placeholder, so the
        label becomes `unknown` and the submission is still counted.
        """
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), form_version="a sentence here")

        assert result.outcome is ProbeOutcome.EMITTED
        attributes = recording.calls[0][1]
        assert attributes["ssf.quality.feedback_form_version"] == "unknown"
        assert "a sentence here" not in str(attributes)

    def test_a_malformed_session_reference_becomes_the_sentinel(self):
        """A raw session id handed here is a bug; storing it would be the leak."""
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), session_ref="ABC12345")

        assert result.outcome is ProbeOutcome.EMITTED
        attributes = recording.calls[0][1]
        assert attributes["ssf.quality.session_ref"] == "0" * 32
        assert "ABC12345" not in str(attributes)


class TestTheCollectorKeepsTheNewKeys:
    """The collector strips anything absent from keep_keys, silently."""

    @pytest.mark.parametrize("key", sorted(NEW_KEYS))
    def test_the_collector_config_keeps_the_key(self, key):
        config = (ROOT / "monitoring/otel-collector-config.yaml").read_text()

        assert f'"{key}"' in config


class TestTheMigrationGivesEveryKeyAColumn:
    """A key with no column vanishes between the collector and the table."""

    @pytest.mark.parametrize("key", sorted(NEW_KEYS))
    def test_the_migration_projects_the_key(self, key):
        migrations = ROOT / "deploy/clickhouse/migrations"
        sql = "\n".join(p.read_text() for p in sorted(migrations.glob("*.sql")))

        assert f"LogAttributes['{key}']" in sql

    def test_a_dedicated_feedback_aggregate_exists(self):
        """Feedback in the refinement-oriented gold table contributes zeros."""
        sql = (ROOT / "deploy/clickhouse/migrations/006_feedback_submitted_fields.sql").read_text()

        assert "CREATE TABLE IF NOT EXISTS feedback_daily" in sql
        assert "uniqExactState(event_id)" in sql


class TestTheTenantDimension:
    """#325: the one quality event that could not be broken down by tenant.

    `translation_message` and `session_lifecycle` have carried `tenant_ref`
    since the tenant-isolation release; feedback was built before it. The
    reference is a bounded, stable SHA-256 prefix, so the column groups by
    tenant without the configured identifier being stored.

    Bounded and stable, not irreversible: unlike `session_ref` and
    `feedback_ref` this digest is unkeyed, and tenant ids are few and
    guessable, so anyone with read access can invert the column by hashing a
    candidate list. That is the deliberate pre-existing choice documented on
    `session_pseudonym.tenant_ref`, not a property this change establishes.
    """

    def test_a_tenant_reference_of_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            _event(tenant_ref="ABC")

    def test_the_reference_reaches_the_exporter(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), tenant_ref=TENANT_REFERENCE)

        assert recording.calls[0][1]["ssf.quality.tenant_ref"] == TENANT_REFERENCE

    def test_a_submission_naming_no_tenant_carries_the_sentinel(self):
        """Absent, not wrong: a row with no tenant must not group under one."""
        recording = _Recording()

        _emit(_telemetry(exporter=recording))

        assert recording.calls[0][1]["ssf.quality.tenant_ref"] == MISSING_TENANT_REFERENCE

    def test_a_raw_tenant_id_becomes_the_sentinel_rather_than_being_stored(self):
        """Handing the id instead of the reference is a bug; storing it is the leak.

        Coerced rather than dropped, matching the sibling emitters: the ratings
        alongside it are valid data, and the tenant has a safe placeholder.
        """
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), tenant_ref="acme-municipality")

        assert result.outcome is ProbeOutcome.EMITTED
        attributes = recording.calls[0][1]
        assert attributes["ssf.quality.tenant_ref"] == MISSING_TENANT_REFERENCE
        assert "acme-municipality" not in str(attributes)

    def test_the_reference_reuses_the_key_its_siblings_write(self):
        """One key, one meaning: a tenant's feedback and its sessions join on it."""
        assert (
            ALLOWED_ATTRIBUTES["ssf.quality.tenant_ref"].kind is AttributeKind.TENANT_REF
        )
        assert "ssf.quality.tenant_ref" in to_otlp_attributes(_event())


class TestTheGoldTableIsDimensionedByTenant:
    """#325: `feedback_daily` could not answer "what is this tenant's NPS".

    006 created the aggregate after 005 had already added the silver column,
    but left tenant out of the sorting key -- reasonably, since nothing emitted
    a reference for a feedback row until now.
    """

    @staticmethod
    def _sql() -> str:
        return (
            ROOT / "deploy/clickhouse/migrations/007_feedback_tenant_dimension.sql"
        ).read_text()

    @staticmethod
    def _first_statement(sql: str, opening: str) -> str:
        start = sql.index(opening)
        return sql[start : sql.index(";", start)]

    def test_the_aggregate_gains_a_tenant_column(self):
        assert re.search(r"ADD COLUMN IF NOT EXISTS\s+tenant_ref\b", self._sql())

    def test_the_column_joins_the_sorting_key(self):
        """Without it in the key the column exists but never splits a row."""
        statement = self._first_statement(self._sql(), "ALTER TABLE feedback_daily")

        assert "MODIFY ORDER BY" in statement
        assert re.search(r"MODIFY ORDER BY \([^)]*\btenant_ref\b[^)]*\)", statement)

    def test_the_column_is_added_by_the_same_statement_that_extends_the_key(self):
        """ClickHouse rejects any other arrangement.

        MODIFY ORDER BY may only append a column the same ALTER added: an
        existing column could already be out of order within a part. Split
        into two statements this reads fine and fails at apply time.
        """
        extending = [s for s in self._sql().split(";") if "MODIFY ORDER BY" in s]

        assert len(extending) == 1
        assert re.search(r"ADD COLUMN IF NOT EXISTS\s+tenant_ref\b", extending[0])

    def test_the_key_column_carries_no_default_expression(self):
        """ClickHouse refuses a sorting-key column with one, at apply time only.

        Every column 002-006 add has `DEFAULT ''`, so copying that habit is the
        natural mistake -- and nothing but a live server rejects it. A String's
        implicit default is already the empty string.
        """
        added = re.search(r"ADD COLUMN IF NOT EXISTS\s+tenant_ref\b[^,;]*", self._sql())

        assert added, "007 does not add tenant_ref"
        assert "DEFAULT" not in added.group(0).upper(), added.group(0)

    def test_the_view_groups_by_tenant(self):
        """A key the view never groups by collapses back to one row."""
        statement = self._first_statement(self._sql(), "ALTER TABLE feedback_daily_mv")
        grouping = statement.split("GROUP BY")[-1]

        assert "tenant_ref" in grouping

    def test_the_earlier_projection_is_left_alone(self):
        """Gold only. Silver's tenant_ref has been projected since 005."""
        statements = "\n".join(
            line for line in self._sql().splitlines() if not line.lstrip().startswith("--")
        )

        assert "quality_events_mv" not in statements
