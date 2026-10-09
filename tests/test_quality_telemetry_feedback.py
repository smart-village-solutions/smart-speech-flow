"""The `feedback_submitted` event: ratings in ClickHouse, text nowhere near it.

The submission is split across two stores. This event is the analytical half:
ratings, NPS and two opaque references. Its whole reason for existing is that
the other half -- the free text -- cannot be represented here at all, which is
enforced by AttributeKind having no free-text member.

`emit_feedback` takes the header's `event_id` from its caller rather than minting
one, unlike every sibling. #305's reconciler re-emits a failed delivery with
the same id, and silver's ReplacingMergeTree plus gold's uniqExactState only
deduplicate if that id is stable.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, uuid5

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    FeedbackAnswer,
    FeedbackHeader,
    QualityTelemetry,
    discard_event,
)
from services.api_gateway.quality_telemetry_schema import (
    ALLOWED_ATTRIBUTE_KEYS,
    ALLOWED_ATTRIBUTES,
    AttributeKind,
    FeedbackAnswerEvent,
    FeedbackAudience,
    FeedbackFormSource,
    FeedbackQuestionType,
    FeedbackSubmittedEvent,
    ProbeOutcome,
    QualityEventType,
    TelemetryMode,
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
    "ssf.quality.audience": AttributeKind.ENUM,
    "ssf.quality.form_source": AttributeKind.ENUM,
    "ssf.quality.feedback_locale": AttributeKind.LANGUAGE,
    "ssf.quality.answer_count": AttributeKind.NUMBER,
    "ssf.quality.question_id": AttributeKind.LABEL,
    "ssf.quality.question_type": AttributeKind.ENUM,
    "ssf.quality.answer_value": AttributeKind.NUMBER,
    "ssf.quality.answer_min": AttributeKind.NUMBER,
    "ssf.quality.answer_max": AttributeKind.NUMBER,
}

RATING_KEYS = {
    "ssf.quality.translation_quality",
    "ssf.quality.performance",
    "ssf.quality.usability",
    "ssf.quality.net_promoter_score",
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
        audience=FeedbackAudience.GUEST,
        form_source=FeedbackFormSource.BUNDLED,
        feedback_locale="en",
        answer_count=4,
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


def _header(**overrides) -> FeedbackHeader:
    fields = dict(
        event_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        session_ref=SESSION_REFERENCE,
        feedback_ref=FEEDBACK_REFERENCE,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        form_version="v1",
        audience="guest",
        form_source="bundled",
        locale="en",
    )
    fields.update(overrides)
    return FeedbackHeader(**fields)


def _answer(**overrides) -> FeedbackAnswer:
    fields = dict(question_id="clarity", question_type="rating", value=4, minimum=1, maximum=7)
    fields.update(overrides)
    return FeedbackAnswer(**fields)


def _emit(telemetry, answers=(), **overrides):
    """A submission's header, and its answers if given, through the one batch call."""
    return telemetry.emit_feedback(_header(**overrides), answers)


def _answer_event(**overrides) -> FeedbackAnswerEvent:
    fields = dict(
        event_id=uuid4(),
        schema_version=1,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type=QualityEventType.FEEDBACK_ANSWER,
        feedback_ref=FEEDBACK_REFERENCE,
        audience=FeedbackAudience.GUEST,
        question_id="clarity",
        question_type=FeedbackQuestionType.RATING,
        value=4,
        minimum=1,
        maximum=7,
    )
    fields.update(overrides)
    return FeedbackAnswerEvent(**fields)


def _emit_answer(telemetry, submission_event_id=None, **overrides):
    """One answer and the header it belongs to."""
    header = _header(event_id=submission_event_id or uuid4())
    return telemetry.emit_feedback(header, [_answer(**overrides)])


def _answers(recording) -> list[dict]:
    return [attributes for name, attributes, _ in recording.calls if name == "feedback_answer"]


class TestTheEventCarriesNoContent:
    def test_every_attribute_is_a_number_an_enum_a_label_or_a_reference(self):
        kinds = {ALLOWED_ATTRIBUTES[key].kind for key in to_otlp_attributes(_event())}

        assert kinds <= {
            AttributeKind.UUID,
            AttributeKind.NUMBER,
            AttributeKind.ENUM,
            AttributeKind.LABEL,
            # The form's locale: a two- or three-letter tag, no room for a word.
            AttributeKind.LANGUAGE,
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


class TestTheHeaderDescribesEveryForm:
    """PR 12: a header for every stored row, with the bundled ratings only when they apply.

    Gold averages the four rating columns, and an absent rating is stored as 0.
    A header that sent zeros for a form without the bundled questions would drag
    every average down and count as an NPS detractor, so the keys are omitted.
    """

    def test_a_header_without_ratings_carries_no_rating_key(self):
        event = _event(
            translation_quality=None, performance=None, usability=None, net_promoter_score=None
        )

        assert not RATING_KEYS & set(to_otlp_attributes(event))

    def test_a_header_with_ratings_carries_all_four(self):
        assert RATING_KEYS <= set(to_otlp_attributes(_event()))

    @pytest.mark.parametrize("field", ["translation_quality", "performance", "usability", "net_promoter_score"])
    def test_a_partial_rating_set_is_rejected(self, field):
        """Half a rating set would read as a real submission with zeros in it."""
        with pytest.raises(ValueError):
            _event(**{field: None})

    def test_audience_form_source_locale_and_count_reach_the_attributes(self):
        attributes = to_otlp_attributes(
            _event(
                audience=FeedbackAudience.STAFF,
                form_source=FeedbackFormSource.STUDIO,
                feedback_locale="de",
                answer_count=7,
            )
        )

        assert attributes["ssf.quality.audience"] == "staff"
        assert attributes["ssf.quality.form_source"] == "studio"
        assert attributes["ssf.quality.feedback_locale"] == "de"
        assert attributes["ssf.quality.answer_count"] == "7"

    def test_a_negative_answer_count_is_rejected(self):
        with pytest.raises(ValueError):
            _event(answer_count=-1)

    def test_the_emitter_sends_no_rating_when_none_is_given(self):
        recording = _Recording()

        result = _emit(
            _telemetry(exporter=recording),
            translation_quality=None,
            performance=None,
            usability=None,
            net_promoter_score=None,
            form_source="studio",
        )

        assert result.outcome is ProbeOutcome.EMITTED
        assert not RATING_KEYS & set(recording.calls[0][1])

    @pytest.mark.parametrize("locale", [None, "zh-Hant-TW", "a sentence"])
    def test_a_locale_that_is_not_a_language_tag_becomes_undetermined(self, locale):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), locale=locale)

        assert recording.calls[0][1]["ssf.quality.feedback_locale"] == "und"

    @pytest.mark.parametrize("field,value", [("audience", "citizen"), ("form_source", "remote")])
    def test_an_unknown_audience_or_source_is_dropped_not_guessed(self, field, value):
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), **{field: value})

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []


class TestTheAnswerEvent:
    def test_it_carries_the_question_and_its_range(self):
        attributes = to_otlp_attributes(_answer_event(tenant_ref=TENANT_REFERENCE))

        assert attributes["ssf.quality.feedback_ref"] == FEEDBACK_REFERENCE
        assert attributes["ssf.quality.tenant_ref"] == TENANT_REFERENCE
        assert attributes["ssf.quality.audience"] == "guest"
        assert attributes["ssf.quality.question_id"] == "clarity"
        assert attributes["ssf.quality.question_type"] == "rating"
        assert attributes["ssf.quality.answer_value"] == "4"
        assert attributes["ssf.quality.answer_min"] == "1"
        assert attributes["ssf.quality.answer_max"] == "7"

    def test_it_carries_no_session_and_no_rating_key(self):
        """The header joins a submission to its session; one copy is enough."""
        attributes = to_otlp_attributes(_answer_event())

        assert "ssf.quality.session_ref" not in attributes
        assert not RATING_KEYS & set(attributes)

    @pytest.mark.parametrize("question_id", ["how was it", "a" * 65, "", "q;drop", "naïve"])
    def test_a_question_id_that_is_not_a_label_is_rejected(self, question_id):
        with pytest.raises(ValueError):
            _answer_event(question_id=question_id)

    def test_the_allowlist_rejects_a_question_id_that_is_not_a_label(self):
        """The shape guard, independent of the event class's own check."""
        from services.api_gateway.quality_telemetry_schema import (
            DisallowedTelemetryValue,
            enforce_value_shapes,
        )

        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes({"ssf.quality.question_id": "what did you think"})

    @pytest.mark.parametrize(
        "value,minimum,maximum", [(0, 1, 5), (6, 1, 5), (3, 5, 5), (3, 5, 1), (300, 0, 400)]
    )
    def test_a_value_outside_a_valid_range_is_rejected(self, value, minimum, maximum):
        with pytest.raises(ValueError):
            _answer_event(value=value, minimum=minimum, maximum=maximum)

    def test_the_wrong_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            _answer_event(event_type=QualityEventType.FEEDBACK_SUBMITTED)


class TestAnswerEmission:
    def test_the_event_id_derives_from_the_submission_and_the_question(self):
        recording = _Recording()
        submission = uuid4()

        result = _emit_answer(
            _telemetry(exporter=recording), submission_event_id=submission, question_id="clarity"
        )

        assert result.outcome is ProbeOutcome.EMITTED
        assert result.event_id == submission
        assert _answers(recording)[0]["ssf.quality.event_id"] == str(uuid5(submission, "clarity"))

    def test_re_emitting_an_answer_repeats_its_id(self):
        """The reconciler re-emits; a fresh id would count the answer twice."""
        recording = _Recording()
        telemetry = _telemetry(exporter=recording)
        submission = uuid4()

        _emit_answer(telemetry, submission_event_id=submission)
        _emit_answer(telemetry, submission_event_id=submission)

        first, second = _answers(recording)
        assert first["ssf.quality.event_id"] == second["ssf.quality.event_id"]

    def test_two_questions_of_one_submission_get_different_ids(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), [_answer(question_id="clarity"), _answer(question_id="speed")])

        first, second = _answers(recording)
        assert first["ssf.quality.event_id"] != second["ssf.quality.event_id"]

    def test_answers_share_the_headers_references_and_audience(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), [_answer()], audience="staff", tenant_ref=TENANT_REFERENCE)

        (answer,) = _answers(recording)
        assert answer["ssf.quality.feedback_ref"] == FEEDBACK_REFERENCE
        assert answer["ssf.quality.tenant_ref"] == TENANT_REFERENCE
        assert answer["ssf.quality.audience"] == "staff"

    def test_the_header_counts_the_answers_it_was_sent_with(self):
        recording = _Recording()

        _emit(_telemetry(exporter=recording), [_answer(question_id="a"), _answer(question_id="b")])

        assert recording.calls[0][1]["ssf.quality.answer_count"] == "2"

    def test_it_emits_under_the_answer_event_name(self):
        recording = _Recording()

        _emit_answer(_telemetry(exporter=recording))

        assert [name for name, _, _ in recording.calls] == ["feedback_submitted", "feedback_answer"]

    def test_a_disabled_deployment_emits_nothing(self):
        recording = _Recording()

        result = _emit_answer(_telemetry(mode=TelemetryMode.DISABLED, exporter=recording))

        assert result.outcome is ProbeOutcome.DISABLED
        assert recording.calls == []

    def test_a_question_id_that_is_not_a_label_is_dropped_and_not_echoed(self, caplog):
        """Never coerced: pooled under a placeholder it would corrupt that average."""
        recording = _Recording()

        result = _emit_answer(_telemetry(exporter=recording), question_id="what did you think")

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []
        assert "what did you think" not in caplog.text

    def test_an_unknown_question_type_is_dropped(self):
        """longText never reaches here; if it did, it must not become a number."""
        recording = _Recording()

        result = _emit_answer(_telemetry(exporter=recording), question_type="longText")

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []


class TestASubmissionIsAllOrNothing:
    """PR #554 review: a rejection must not leave the accepted events to be re-sent.

    The schema rejects the same event on every attempt, so the row is marked
    final; anything sent before the rejection would have been sent for good,
    and re-sending it on every pass re-adds it to gold's averages.
    """

    def test_one_rejected_answer_sends_nothing_at_all(self):
        recording = _Recording()

        result = _emit(
            _telemetry(exporter=recording),
            [_answer(question_id="clarity"), _answer(question_id="speed", value=99, maximum=10)],
        )

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []

    def test_a_rejected_header_sends_no_answer(self):
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), [_answer()], translation_quality=99)

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []

    def test_a_rejection_is_counted_once_so_the_alert_fires(self):
        registry = CollectorRegistry()
        telemetry = QualityTelemetry(mode=TelemetryMode.ENABLED, exporter=_Recording(), registry=registry)

        telemetry.emit_feedback(_header(), [_answer(value=99)])

        assert registry.get_sample_value(
            "ssf_quality_telemetry_events_total", {"outcome": "dropped_disallowed"}
        ) == 1

    def test_every_sent_event_is_counted_so_the_collector_gap_stays_honest(self):
        """QualityTelemetryEventsLostBeforeCollector compares this count with
        the records the collector accepted, which counts every event."""
        registry = CollectorRegistry()
        telemetry = QualityTelemetry(mode=TelemetryMode.ENABLED, exporter=_Recording(), registry=registry)

        telemetry.emit_feedback(_header(), [_answer(question_id="a"), _answer(question_id="b")])

        assert registry.get_sample_value(
            "ssf_quality_telemetry_events_total", {"outcome": "emitted"}
        ) == 3

    def test_an_export_failure_still_sends_the_rest_and_asks_for_a_retry(self):
        sent = []

        def flaky(name, attributes, emitted_at_utc):
            if attributes.get("ssf.quality.question_id") == "a":
                raise ConnectionError("collector unreachable")
            sent.append(name)

        result = QualityTelemetry(
            mode=TelemetryMode.ENABLED, exporter=flaky, registry=CollectorRegistry()
        ).emit_feedback(_header(), [_answer(question_id="a"), _answer(question_id="b")])

        assert result.outcome is ProbeOutcome.EXPORT_FAILED
        assert sent == ["feedback_submitted", "feedback_answer"]

    def test_every_event_is_stamped_with_the_submission_time(self):
        """A re-send lands on the submission's gold day and renews no silver TTL."""
        recording = _Recording()
        submitted = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)

        _emit(_telemetry(exporter=recording), [_answer()], occurred_at=submitted)

        assert {emitted_at for _, _, emitted_at in recording.calls} == {submitted}

    def test_a_naive_submission_time_is_rejected_not_guessed(self):
        recording = _Recording()

        result = _emit(_telemetry(exporter=recording), occurred_at=datetime(2026, 10, 1, 9, 30))

        assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
        assert recording.calls == []


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


class TestTheFeedbackGoldTiersAfterPr12:
    """008: header events for every form, answer events, and an audience split.

    `feedback_daily_mv` averaged the four rating columns over every header, and
    an absent rating is 0. Once forms without the bundled ids send headers,
    those zeros would drag every average down and every such row would count
    as an NPS detractor. 008 moves gold to `feedback_daily_v2`, whose averages
    and NPS see only rows that carry the ratings.
    """

    MIGRATION = ROOT / "deploy/clickhouse/migrations/008_feedback_answers_and_audience.sql"

    @classmethod
    def _statements(cls) -> list[str]:
        sql = "\n".join(
            line for line in cls.MIGRATION.read_text().splitlines() if not line.lstrip().startswith("--")
        )
        return [" ".join(statement.split()) for statement in sql.split(";") if statement.strip()]

    @classmethod
    def _statement(cls, opening: str) -> str:
        matching = [statement for statement in cls._statements() if statement.startswith(opening)]
        assert len(matching) == 1, (opening, matching)
        return matching[0]

    def test_silver_gains_the_legacy_flag_derived_from_the_ratings(self):
        """Every pre-PR-12 header carried ratings, so old rows must read 1."""
        added = self._statement("ALTER TABLE quality_events ADD COLUMN")

        assert re.search(r"has_legacy_ratings UInt8 DEFAULT toUInt8\(translation_quality > 0\)", added)

    def test_the_view_derives_the_flag_from_the_rating_key(self):
        view = self._statement("ALTER TABLE quality_events_mv MODIFY QUERY")

        assert (
            "toUInt8(LogAttributes['ssf.quality.translation_quality'] != '') AS has_legacy_ratings"
            in view
        )

    def test_gold_v2_is_keyed_by_audience_and_form_source(self):
        """A new table, not MODIFY ORDER BY: a re-run of 007 shrinks an
        extended key back without an error (verified on 26.3.17)."""
        table = self._statement("CREATE TABLE IF NOT EXISTS feedback_daily_v2 ")
        key = re.search(r"ORDER BY \(([^)]*)\)", table).group(1)

        assert [column.strip() for column in key.split(",")][-3:] == [
            "tenant_ref",
            "audience",
            "form_source",
        ]
        assert not any(
            statement.startswith("ALTER TABLE feedback_daily ") for statement in self._statements()
        )

    @pytest.mark.parametrize(
        "state",
        [
            "avgStateIf(translation_quality, has_legacy_ratings = 1)",
            "avgStateIf(performance, has_legacy_ratings = 1)",
            "avgStateIf(usability, has_legacy_ratings = 1)",
            "avgStateIf(net_promoter_score, has_legacy_ratings = 1)",
            "uniqExactStateIf(event_id, has_legacy_ratings = 1) AS rated_submissions",
            "uniqExactStateIf(event_id, has_legacy_ratings = 1 AND net_promoter_score >= 9)",
            "uniqExactStateIf(event_id, has_legacy_ratings = 1 AND net_promoter_score <= 6)",
        ],
    )
    def test_the_v2_view_sees_ratings_only_on_rows_that_carry_them(self, state):
        view = self._statement("CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_daily_v2_mv")

        assert state in view

    def test_the_v2_view_counts_every_submission(self):
        view = self._statement("CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_daily_v2_mv")

        assert "uniqExactState(event_id) AS submissions" in view
        assert "WHERE event_type = 'feedback_submitted'" in view
        assert view.split("GROUP BY")[-1].split(",")[-2:] == [" audience", " form_source"]

    def test_the_old_gold_view_is_retired(self):
        assert "DROP VIEW IF EXISTS feedback_daily_mv" in self._statements()

    def test_old_gold_is_copied_into_v2_at_most_once(self):
        """A plain INSERT would re-copy on every apply.sh run and double the averages."""
        copy = self._statement("INSERT INTO feedback_daily_v2 SELECT")

        assert "FROM feedback_daily " in copy + " "
        assert "(SELECT count() FROM feedback_daily_v2_backfill) = 0" in copy
        assert any(
            statement.startswith("INSERT INTO feedback_daily_v2_backfill")
            and "(SELECT count() FROM feedback_daily_v2_backfill) = 0" in statement
            for statement in self._statements()
        )

    def test_the_answer_aggregate_counts_distinct_answers_per_question(self):
        table = self._statement("CREATE TABLE IF NOT EXISTS feedback_answer_daily ")
        view = self._statement("CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_answer_daily_mv")

        for column in ("audience", "question_id", "question_type", "answer_min", "answer_max"):
            assert column in re.search(r"ORDER BY \(([^)]*)\)", table).group(1)
        assert "uniqExactState(event_id) AS answers" in view
        assert "avgState(answer_value) AS value_avg" in view
        assert "WHERE event_type = 'feedback_answer'" in view

    def test_every_create_is_guarded(self):
        unguarded = re.findall(
            r"CREATE (?:TABLE|MATERIALIZED VIEW)(?! IF NOT EXISTS)", self.MIGRATION.read_text()
        )
        assert not unguarded
