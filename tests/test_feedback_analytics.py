"""One stored submission's analytics: a header and one event per numeric answer.

The submit path and the reconciler both go through `emit_submission`, so a
re-emission sends exactly the events the first attempt did, under the same
ids. These tests use the real `QualityTelemetry` with a recording exporter, so
the allowlist and the event classes are exercised, not a fake of them.
"""

from datetime import datetime, timezone
from uuid import uuid4, uuid5

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.feedback.analytics import NumericAnswer, emit_submission, numeric_answers
from services.api_gateway.feedback.bundled_form import bundled_rules
from services.api_gateway.feedback.repository import PendingAnalytics
from services.api_gateway.quality_telemetry import QualityTelemetry
from services.api_gateway.quality_telemetry_schema import ProbeOutcome, TelemetryMode
from services.api_gateway.session_pseudonym import SessionPseudonymizer, tenant_ref

PSEUDONYMIZER = SessionPseudonymizer(key=b"feedback-analytics-test")
SECRET_TEXT = "the interpreter was rude to me"

STUDIO_SNAPSHOT = [
    {"id": "clarity", "type": "rating", "required": True, "min": 1, "max": 7},
    {"id": "comments", "type": "longText", "required": False, "maxLength": 4000},
    {"id": "recommendation", "type": "scale", "required": False, "min": 0, "max": 10},
    {"id": "speed", "type": "scale", "required": False, "min": 0, "max": 10},
]


class _Recording:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._fail_on = fail_on

    def __call__(self, name, attributes, emitted_at_utc):
        if self._fail_on and attributes.get("ssf.quality.question_id") == self._fail_on:
            raise ConnectionError("collector unreachable")
        self.calls.append((name, dict(attributes)))


def _telemetry(exporter, mode=TelemetryMode.ENABLED) -> QualityTelemetry:
    return QualityTelemetry(mode=mode, exporter=exporter, registry=CollectorRegistry())


def _row(**overrides) -> PendingAnalytics:
    fields = dict(
        feedback_id=uuid4(),
        tenant_id="tenant-a",
        session_ref="c" * 32,
        analytics_event_id=uuid4(),
        audience="guest",
        form_source="studio",
        form_locale="en",
        numeric_answers={"clarity": 6, "recommendation": 3},
        form_snapshot=STUDIO_SNAPSHOT,
        form_version="v2",
        created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return PendingAnalytics(**fields)


def _bundled_row(**overrides) -> PendingAnalytics:
    fields = dict(
        form_source="bundled",
        numeric_answers={
            "translationQuality": 4,
            "performance": 5,
            "usability": 3,
            "recommendation": 9,
        },
        form_snapshot=list(bundled_rules().snapshot),
    )
    fields.update(overrides)
    return _row(**fields)


class TestNumericAnswers:
    def test_answers_follow_the_form_order_with_their_ranges(self):
        assert numeric_answers({"recommendation": 3, "clarity": 6}, STUDIO_SNAPSHOT) == (
            NumericAnswer("clarity", "rating", 6, 1, 7),
            NumericAnswer("recommendation", "scale", 3, 0, 10),
        )

    def test_unanswered_and_text_questions_produce_nothing(self):
        assert numeric_answers({}, STUDIO_SNAPSHOT) == ()

    def test_an_answer_the_form_did_not_ask_is_ignored(self):
        """The snapshot is the form as validated; it decides what an answer is."""
        assert numeric_answers({"stray": 3}, STUDIO_SNAPSHOT) == ()


class TestTheHeader:
    def test_every_row_gets_a_header_with_its_form_and_audience(self):
        recording = _Recording()
        row = _row(audience="staff", form_locale="de")

        outcome = emit_submission(_telemetry(recording), PSEUDONYMIZER, row)

        assert outcome is ProbeOutcome.EMITTED
        name, header = recording.calls[0]
        assert name == "feedback_submitted"
        assert header["ssf.quality.event_id"] == str(row.analytics_event_id)
        assert header["ssf.quality.audience"] == "staff"
        assert header["ssf.quality.form_source"] == "studio"
        assert header["ssf.quality.feedback_locale"] == "de"
        assert header["ssf.quality.answer_count"] == "2"
        assert header["ssf.quality.tenant_ref"] == tenant_ref("tenant-a")
        assert header["ssf.quality.feedback_ref"] == PSEUDONYMIZER.feedback_reference(
            row.feedback_id
        )

    def test_a_form_without_the_bundled_questions_sends_no_rating(self):
        """Its zeros would drag gold's averages down and count as detractors."""
        recording = _Recording()

        emit_submission(_telemetry(recording), PSEUDONYMIZER, _row())

        header = recording.calls[0][1]
        assert "ssf.quality.translation_quality" not in header
        assert "ssf.quality.net_promoter_score" not in header

    def test_the_bundled_form_sends_its_four_ratings(self):
        recording = _Recording()

        emit_submission(_telemetry(recording), PSEUDONYMIZER, _bundled_row())

        header = recording.calls[0][1]
        assert header["ssf.quality.translation_quality"] == "4"
        assert header["ssf.quality.performance"] == "5"
        assert header["ssf.quality.usability"] == "3"
        assert header["ssf.quality.net_promoter_score"] == "9"

    def test_a_v1_row_without_a_locale_is_undetermined(self):
        recording = _Recording()

        emit_submission(_telemetry(recording), PSEUDONYMIZER, _bundled_row(form_locale=None))

        assert recording.calls[0][1]["ssf.quality.feedback_locale"] == "und"


class TestTheAnswers:
    def test_one_event_per_numeric_answer_under_derived_ids(self):
        recording = _Recording()
        row = _row()

        emit_submission(_telemetry(recording), PSEUDONYMIZER, row)

        answers = [attributes for name, attributes in recording.calls if name == "feedback_answer"]
        assert [a["ssf.quality.question_id"] for a in answers] == ["clarity", "recommendation"]
        assert [a["ssf.quality.event_id"] for a in answers] == [
            str(uuid5(row.analytics_event_id, "clarity")),
            str(uuid5(row.analytics_event_id, "recommendation")),
        ]
        assert answers[0]["ssf.quality.answer_value"] == "6"
        assert answers[0]["ssf.quality.answer_min"] == "1"
        assert answers[0]["ssf.quality.answer_max"] == "7"
        assert answers[0]["ssf.quality.audience"] == "guest"
        assert (
            answers[0]["ssf.quality.feedback_ref"]
            == recording.calls[0][1]["ssf.quality.feedback_ref"]
        )

    def test_re_emitting_a_row_repeats_every_id(self):
        """Reconciliation idempotency at the source: gold counts distinct ids."""
        recording = _Recording()
        telemetry = _telemetry(recording)
        row = _bundled_row()

        emit_submission(telemetry, PSEUDONYMIZER, row)
        first = [attributes["ssf.quality.event_id"] for _, attributes in recording.calls]
        emit_submission(telemetry, PSEUDONYMIZER, row)
        second = [attributes["ssf.quality.event_id"] for _, attributes in recording.calls[5:]]

        assert len(first) == 5  # the header and four answers
        assert first == second
        assert len(set(first)) == 5

    def test_no_event_carries_the_free_text(self):
        """The text lives encrypted in Postgres; nothing here could reach it."""
        recording = _Recording()
        row = _row(numeric_answers={"clarity": 6})

        emit_submission(_telemetry(recording), PSEUDONYMIZER, row)

        everything = repr(recording.calls)
        assert SECRET_TEXT not in everything
        assert "comments" not in everything


class TestTheOutcome:
    def test_a_disabled_deployment_attempts_no_answer(self):
        recording = _Recording()

        outcome = emit_submission(
            _telemetry(recording, mode=TelemetryMode.DISABLED), PSEUDONYMIZER, _row()
        )

        assert outcome is ProbeOutcome.DISABLED
        assert recording.calls == []

    def test_one_failed_answer_leaves_the_row_for_the_reconciler(self):
        recording = _Recording(fail_on="recommendation")

        outcome = emit_submission(_telemetry(recording), PSEUDONYMIZER, _row())

        assert outcome is ProbeOutcome.EXPORT_FAILED

    @pytest.mark.parametrize("audience", ["guest", "staff", "installation"])
    def test_every_audience_is_emitted(self, audience):
        recording = _Recording()

        outcome = emit_submission(_telemetry(recording), PSEUDONYMIZER, _row(audience=audience))

        assert outcome is ProbeOutcome.EMITTED
        assert {a["ssf.quality.audience"] for _, a in recording.calls} == {audience}


class TestARejectionIsReported:
    """A rejected event leaves the row failed, so the reconciliation alert sees it."""

    def test_a_rejected_answer_is_reported_as_rejected(self):
        recording = _Recording()
        row = _row(form_snapshot=[{"id": "how was it", "type": "rating", "min": 1, "max": 7}],
                   numeric_answers={"how was it": 3})

        outcome = emit_submission(_telemetry(recording), PSEUDONYMIZER, row)

        assert outcome is ProbeOutcome.DROPPED_DISALLOWED

    def test_a_transient_failure_outranks_a_rejection(self):
        """Retry while anything could still go out; the next pass settles it."""
        recording = _Recording(fail_on="clarity")
        row = _row(
            form_snapshot=[{"id": "how was it", "type": "rating", "min": 1, "max": 7}, *STUDIO_SNAPSHOT],
            numeric_answers={"clarity": 6, "how was it": 3},
        )

        outcome = emit_submission(_telemetry(recording), PSEUDONYMIZER, row)

        assert outcome is ProbeOutcome.EXPORT_FAILED
