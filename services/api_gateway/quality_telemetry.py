"""Typed, allowlisted quality telemetry contract.

This module must never import the OTel SDK (that lives only in
quality_telemetry_otlp.py) and must never accept a dict from the pipeline: the
pipeline's debug_info carries source text, transcripts and raw errors, and must
not be reachable from here. See
openspec/changes/add-clickhouse-quality-telemetry/design.md.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, TypedDict, Unpack
from uuid import UUID, uuid4, uuid5

from prometheus_client import CollectorRegistry, Counter

from .quality_telemetry_schema import (
    _EVENT_REJECTED,
    _LABEL_PATTERN,
    _LANGUAGE_PATTERN,
    _OPAQUE_REF_PATTERN,
    _TENANT_REF_PATTERN,
    SCHEMA_VERSION,
    DisallowedTelemetryAttribute,
    DisallowedTelemetryValue,
    FeedbackAnswerEvent,
    FeedbackAudience,
    FeedbackFormSource,
    FeedbackQuestionType,
    FeedbackSubmittedEvent,
    InputMode,
    MessageDirection,
    PipelineStage,
    ProbeOutcome,
    ProbeResult,
    QualityErrorCode,
    QualityEvent,
    QualityEventType,
    QualityProbeEvent,
    RefinementAttemptEvent,
    RefinementOutcomeCode,
    RefinerRole,
    SessionLifecycleEvent,
    SessionLifecyclePhase,
    SessionTerminationReason,
    TelemetryMode,
    TerminalOutcome,
    TranslationMessageEvent,
    logger,
    to_otlp_attributes,
)
from .session_pseudonym import MISSING_TENANT_REFERENCE

UNDETERMINED_LANGUAGE: Final[str] = "und"
UNKNOWN_LABEL: Final[str] = "unknown"
# Same width and charset as a real reference so it passes the OPAQUE_REF shape;
# no HMAC will collide with it. Mirrors session_pseudonym.MISSING_REFERENCE.
UNKNOWN_REFERENCE: Final[str] = "0" * 32


def _as_label(value: str) -> str:
    return value if _LABEL_PATTERN.match(str(value or "")) else UNKNOWN_LABEL


def _as_opaque_ref(value: str) -> str:
    """Anything that is not already a reference becomes the missing sentinel.

    A caller that hands this a raw session id has a bug, and storing the id
    would be the exact leak the module exists to prevent -- so it is discarded
    rather than repaired here.
    """
    return value if _OPAQUE_REF_PATTERN.match(str(value or "")) else UNKNOWN_REFERENCE


def _as_tenant_ref(value: str) -> str:
    return value if _TENANT_REF_PATTERN.match(str(value)) else MISSING_TENANT_REFERENCE


def _optional_int(value: int | None) -> int | None:
    return None if value is None else int(value)


def _as_language(value: str) -> str:
    """ISO 639-2's `und` is the standard way to say "not determined"."""
    return value if _LANGUAGE_PATTERN.match(str(value or "")) else UNDETERMINED_LANGUAGE


def classify_upstream_status(status_code: int) -> QualityErrorCode:
    """Reduce an upstream HTTP status to a stable, storable token."""
    if 200 <= status_code < 300:
        return QualityErrorCode.NONE
    if status_code == 503:
        return QualityErrorCode.UPSTREAM_BUSY
    if status_code in (408, 504):
        return QualityErrorCode.UPSTREAM_TIMEOUT
    if 400 <= status_code < 500:
        return QualityErrorCode.UPSTREAM_REJECTED
    if 500 <= status_code < 600:
        return QualityErrorCode.UPSTREAM_ERROR
    return QualityErrorCode.UNKNOWN


# Matched by class name rather than by import so this module stays free of the
# HTTP client: requests' Timeout and ConnectionError are not the builtins.
_TIMEOUT_NAMES: Final[frozenset[str]] = frozenset(
    {"TimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout", "ReadTimeoutError"}
)
_UNREACHABLE_NAMES: Final[frozenset[str]] = frozenset(
    {"ConnectionError", "NewConnectionError", "ProxyError", "SSLError"}
)
_MALFORMED_NAMES: Final[frozenset[str]] = frozenset(
    {"JSONDecodeError", "ValueError", "ContentDecodingError"}
)


def classify_exception(exception: BaseException) -> QualityErrorCode:
    """Reduce an exception to a stable token, never carrying its message."""
    names = {klass.__name__ for klass in type(exception).__mro__}
    if names & _TIMEOUT_NAMES:
        return QualityErrorCode.UPSTREAM_TIMEOUT
    if names & _UNREACHABLE_NAMES:
        return QualityErrorCode.UPSTREAM_UNREACHABLE
    if names & _MALFORMED_NAMES:
        return QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE
    return QualityErrorCode.INTERNAL_ERROR


_EVENTS_COUNTER_NAME = "ssf_quality_telemetry_events_total"


def _events_counter(registry: CollectorRegistry) -> Counter:
    """Register the counter once per registry, reusing it on repeat calls.

    app.py's lifespan builds a fresh QualityTelemetry on every startup, but
    the app's CollectorRegistry, built by create_app(), outlives a single
    lifespan cycle: a test suite spins up many TestClient instances against
    the same app within one process, re-entering lifespan each time.
    prometheus_client raises on a second registration of the same metric name,
    so this mirrors create_app()'s own precedent of registering a series once
    and reusing it thereafter.

    Registration is attempted through the public API first, and every fallback
    ends in a counter rather than an exception. Telemetry is optional; a
    registry this cannot register into must not be able to stop the gateway.
    """
    try:
        return Counter(
            _EVENTS_COUNTER_NAME,
            "Quality telemetry events by outcome",
            ["outcome"],
            registry=registry,
        )
    except ValueError:
        pass  # already registered on this registry, or the name is taken

    # _names_to_collectors is private and may be renamed by a library bump, so
    # reuse is best-effort and never the only path out of here.
    existing = getattr(registry, "_names_to_collectors", {}).get(_EVENTS_COUNTER_NAME)
    if isinstance(existing, Counter):
        return existing

    # The name is held by something that is not our counter. Count into an
    # unregistered collector rather than raising: the series will not be
    # scraped, which is a reporting gap, not an outage.
    logger.warning(
        "%s is not available on the gateway registry; telemetry counters will not be scraped",
        _EVENTS_COUNTER_NAME,
    )
    return Counter(
        _EVENTS_COUNTER_NAME,
        "Quality telemetry events by outcome",
        ["outcome"],
        registry=CollectorRegistry(),
    )


def discard_event(event_name: str, attributes: Mapping[str, str], emitted_at_utc: datetime) -> None:
    """The exporter used in disabled mode.

    `emit_probe` returns before reaching it, so it exists only to keep the
    exporter argument non-optional: a nullable exporter would put the
    "is telemetry on?" test in two places.
    """


class _TranslationDurationArguments(TypedDict):
    total_duration_ms: int
    asr_duration_ms: int
    translation_duration_ms: int
    refinement_duration_ms: int
    tts_duration_ms: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _TranslationDurations:
    total_duration_ms: int
    asr_duration_ms: int
    translation_duration_ms: int
    refinement_duration_ms: int
    tts_duration_ms: int


class QualityTelemetry:
    """Emits allowlisted quality events. Never raises to its caller.

    The exporter is a constructor argument so that a failing ClickHouse can be
    simulated without a container. The registry is injected because the gateway
    keeps its own CollectorRegistry (app.state.prometheus_registry) and
    duplicate registration against the global default is a known failure mode
    in this codebase.
    """

    def __init__(
        self,
        *,
        mode: TelemetryMode,
        exporter: Callable[[str, Mapping[str, str], datetime], None],
        registry: CollectorRegistry,
    ) -> None:
        self._mode = mode
        self._exporter = exporter
        self._events = _events_counter(registry)

    def emit_probe(self, *, event_type: str) -> ProbeResult:
        if self._mode is TelemetryMode.DISABLED:
            # Counted, not just returned: disabled is the production default, so
            # a scrape with no series at all cannot distinguish "off on purpose"
            # from "never wired up".
            return self._record(ProbeOutcome.DISABLED, None)

        return self._export(
            QualityProbeEvent(
                event_id=uuid4(),
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=event_type,
            )
        )

    def emit_refinement_attempt(
        self,
        *,
        refiner_role: RefinerRole,
        model_ref: str,
        outcome: RefinementOutcomeCode,
        latency_ms: int,
        changed: bool,
        source_lang: str,
        target_lang: str,
        error_code: QualityErrorCode,
    ) -> ProbeResult:
        """One shadow or primary refinement attempt.

        Gated on ENABLED, not on "not DISABLED": PROBE stays a pure transport
        check so an operator can verify the pipeline without switching on
        production event volume.

        Every argument is coerced rather than trusted. A model name or language
        the manifest would reject becomes a placeholder instead of dropping the
        event: a missing row makes the denominator wrong for every ratio built
        on it, which is a worse failure than an imprecise label.
        """
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        try:
            event = RefinementAttemptEvent(
                event_id=uuid4(),
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.REFINEMENT_ATTEMPT,
                refiner_role=refiner_role,
                model_ref=_as_label(model_ref),
                outcome=outcome,
                latency_ms=max(0, int(latency_ms or 0)),
                changed=bool(changed),
                source_lang=_as_language(source_lang),
                target_lang=_as_language(target_lang),
                error_code=error_code,
            )
        except (ValueError, TypeError):
            logger.warning(_EVENT_REJECTED)
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, None)

        return self._export(event)

    def emit_translation_message(
        self,
        *,
        session_ref: str,
        direction: MessageDirection,
        input_mode: InputMode,
        source_lang: str,
        target_lang: str,
        terminal_outcome: TerminalOutcome,
        failed_stage: PipelineStage,
        error_code: QualityErrorCode,
        tenant_ref: str = MISSING_TENANT_REFERENCE,
        **durations: Unpack[_TranslationDurationArguments],
    ) -> ProbeResult:
        """One processed message, successful or not.

        Gated on ENABLED for the same reason as the refinement event: PROBE
        stays a pure transport check. Every argument is coerced rather than
        trusted, because this is the row every ratio divides by and a dropped
        row makes each of those ratios wrong for as long as it is retained.
        """
        # Preserve required keyword validation even while telemetry is disabled.
        timing = _TranslationDurations(**durations)
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        try:
            event = TranslationMessageEvent(
                event_id=uuid4(),
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.TRANSLATION_MESSAGE,
                session_ref=_as_opaque_ref(session_ref),
                tenant_ref=(
                    tenant_ref
                    if _TENANT_REF_PATTERN.match(str(tenant_ref))
                    else MISSING_TENANT_REFERENCE
                ),
                direction=direction,
                input_mode=input_mode,
                source_lang=_as_language(source_lang),
                target_lang=_as_language(target_lang),
                terminal_outcome=terminal_outcome,
                failed_stage=failed_stage,
                error_code=error_code,
                total_duration_ms=max(0, int(timing.total_duration_ms or 0)),
                asr_duration_ms=max(0, int(timing.asr_duration_ms or 0)),
                translation_duration_ms=max(0, int(timing.translation_duration_ms or 0)),
                refinement_duration_ms=max(0, int(timing.refinement_duration_ms or 0)),
                tts_duration_ms=max(0, int(timing.tts_duration_ms or 0)),
            )
        except (ValueError, TypeError):
            logger.warning(_EVENT_REJECTED)
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, None)

        return self._export(event)

    def emit_session_lifecycle(
        self,
        *,
        session_ref: str,
        phase: SessionLifecyclePhase,
        termination_reason: SessionTerminationReason,
        session_duration_ms: int,
        message_count: int,
        tenant_ref: str = MISSING_TENANT_REFERENCE,
    ) -> ProbeResult:
        """One session transition.

        Gated on ENABLED like the other pipeline events. Coerces rather than
        trusts: this is the denominator for every per-session ratio, and a
        dropped row makes each of them wrong for as long as it is retained.
        """
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        try:
            event = SessionLifecycleEvent(
                event_id=uuid4(),
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.SESSION_LIFECYCLE,
                session_ref=_as_opaque_ref(session_ref),
                tenant_ref=(
                    tenant_ref
                    if _TENANT_REF_PATTERN.match(str(tenant_ref))
                    else MISSING_TENANT_REFERENCE
                ),
                phase=phase,
                termination_reason=termination_reason,
                session_duration_ms=max(0, int(session_duration_ms or 0)),
                message_count=max(0, int(message_count or 0)),
            )
        except (ValueError, TypeError):
            logger.warning(_EVENT_REJECTED)
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, None)

        return self._export(event)

    def emit_feedback_submitted(
        self,
        *,
        event_id: UUID,
        session_ref: str,
        feedback_ref: str,
        audience: str,
        form_source: str,
        locale: str | None,
        answer_count: int,
        form_version: str,
        tenant_ref: str = MISSING_TENANT_REFERENCE,
        translation_quality: int | None = None,
        performance: int | None = None,
        usability: int | None = None,
        net_promoter_score: int | None = None,
    ) -> ProbeResult:
        """The header of one stored submission, structured half only.

        Unlike its siblings this takes `event_id` from the caller rather than
        minting one. #305's reconciler re-emits a failed delivery with the same
        id, and silver's ReplacingMergeTree plus gold's uniqExactState(event_id)
        deduplicate only if that id is stable across attempts.

        The four ratings are passed only when the form asked the bundled
        questions; see FeedbackSubmittedEvent. There is no parameter for the
        free text, and no allowlisted key that could carry it.
        """
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        try:
            event = FeedbackSubmittedEvent(
                event_id=event_id,
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.FEEDBACK_SUBMITTED,
                session_ref=_as_opaque_ref(session_ref),
                tenant_ref=_as_tenant_ref(tenant_ref),
                feedback_ref=_as_opaque_ref(feedback_ref),
                feedback_form_version=_as_label(form_version),
                audience=FeedbackAudience(audience),
                form_source=FeedbackFormSource(form_source),
                feedback_locale=_as_language(locale or ""),
                answer_count=int(answer_count),
                translation_quality=_optional_int(translation_quality),
                performance=_optional_int(performance),
                usability=_optional_int(usability),
                net_promoter_score=_optional_int(net_promoter_score),
            )
        except (ValueError, TypeError):
            logger.warning(_EVENT_REJECTED)
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, event_id)

        return self._export(event)

    def emit_feedback_answer(
        self,
        *,
        submission_event_id: UUID,
        feedback_ref: str,
        audience: str,
        question_id: str,
        question_type: str,
        value: int,
        minimum: int,
        maximum: int,
        tenant_ref: str = MISSING_TENANT_REFERENCE,
    ) -> ProbeResult:
        """One answered numeric question, under an id derived from its submission.

        The id is computed here rather than by the caller so the submit path
        and the reconciler cannot derive it differently. A question id that is
        not a label is dropped, never coerced: pooled under a placeholder, it
        would corrupt that placeholder's average.
        """
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        event_id = uuid5(submission_event_id, str(question_id))
        try:
            event = FeedbackAnswerEvent(
                event_id=event_id,
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.FEEDBACK_ANSWER,
                feedback_ref=_as_opaque_ref(feedback_ref),
                tenant_ref=_as_tenant_ref(tenant_ref),
                audience=FeedbackAudience(audience),
                question_id=question_id,
                question_type=FeedbackQuestionType(question_type),
                value=int(value),
                minimum=int(minimum),
                maximum=int(maximum),
            )
        except (ValueError, TypeError):
            logger.warning(_EVENT_REJECTED)
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, event_id)

        return self._export(event)

    def _export(self, event: QualityEvent) -> ProbeResult:
        event_type = event.event_type
        name = event_type.value if isinstance(event_type, Enum) else str(event_type)
        try:
            self._exporter(name, to_otlp_attributes(event), event.emitted_at_utc)
        except (DisallowedTelemetryAttribute, DisallowedTelemetryValue):
            logger.warning("Quality telemetry attribute rejected by the allowlist")
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, event.event_id)
        except Exception:  # telemetry must never reach the caller
            logger.warning("Quality telemetry export failed", exc_info=True)
            return self._record(ProbeOutcome.EXPORT_FAILED, event.event_id)

        return self._record(ProbeOutcome.EMITTED, event.event_id)

    def _record(self, outcome: ProbeOutcome, event_id: UUID | None) -> ProbeResult:
        self._events.labels(outcome=outcome.value).inc()
        return ProbeResult(outcome, event_id)

    @property
    def mode(self) -> TelemetryMode:
        return self._mode
