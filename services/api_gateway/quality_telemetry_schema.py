"""The quality-telemetry contract: event types and taxonomies, the attribute allowlist, the event records, and the checks that keep content out of them."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final
from uuid import UUID

from .session_pseudonym import MISSING_TENANT_REFERENCE

logger = logging.getLogger(__name__)

SCHEMA_VERSION: Final[int] = 1

_SOURCE_LANG_ATTRIBUTE: Final = "ssf.quality.source_lang"
_TARGET_LANG_ATTRIBUTE: Final = "ssf.quality.target_lang"
_ERROR_CODE_ATTRIBUTE: Final = "ssf.quality.error_code"
_SESSION_REF_ATTRIBUTE: Final = "ssf.quality.session_ref"
_TENANT_REF_ATTRIBUTE: Final = "ssf.quality.tenant_ref"
_FEEDBACK_REF_ATTRIBUTE: Final = "ssf.quality.feedback_ref"
_AUDIENCE_ATTRIBUTE: Final = "ssf.quality.audience"
_INVALID_SESSION_REF: Final = "session_ref is not an opaque reference"
_INVALID_TENANT_REF: Final = "tenant_ref is not a bounded tenant reference"
_INVALID_FEEDBACK_REF: Final = "feedback_ref is not an opaque reference"
_EVENT_REJECTED: Final = "Quality telemetry event rejected before export"


class QualityEventType(str, Enum):
    """The closed set of event types this pipeline knows how to store."""

    TELEMETRY_PROBE = "telemetry_probe"
    REFINEMENT_ATTEMPT = "refinement_attempt"
    TRANSLATION_MESSAGE = "translation_message"
    SESSION_LIFECYCLE = "session_lifecycle"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    FEEDBACK_ANSWER = "feedback_answer"


class QualityErrorCode(str, Enum):
    """Stable failure classification (task 1.1).

    A raw upstream message must never reach ClickHouse, so every failure is
    reduced to one of these tokens before it is emitted. Values are part of the
    stored contract: rename one and every historical row disagrees with it.
    """

    NONE = "none"
    UPSTREAM_BUSY = "upstream_busy"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNREACHABLE = "upstream_unreachable"
    UPSTREAM_REJECTED = "upstream_rejected"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_MALFORMED_RESPONSE = "upstream_malformed_response"
    # The breaker refused before a request was sent, so there is no
    # upstream reply to classify. Distinct from UPSTREAM_BUSY: that one is
    # a working service shedding load, this one is a service we have
    # stopped calling.
    UPSTREAM_CIRCUIT_OPEN = "upstream_circuit_open"
    AUDIO_VALIDATION_FAILED = "audio_validation_failed"
    # ASR answered, but with nothing but whitespace. Not an upstream fault.
    NO_SPEECH_RECOGNIZED = "no_speech_recognized"
    TEXT_VALIDATION_FAILED = "text_validation_failed"
    CONTENT_REJECTED = "content_rejected"
    REFINEMENT_OVERLOADED = "refinement_overloaded"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"


class PipelineStage(str, Enum):
    """Where in the pipeline a terminal outcome was decided."""

    NONE = "none"
    VALIDATION = "validation"
    ASR = "asr"
    TRANSLATION = "translation"
    REFINEMENT = "refinement"
    TTS = "tts"
    DELIVERY = "delivery"
    # Shed before any stage ran. Distinct from VALIDATION: the request was
    # well formed, the gateway was simply at capacity, and folding the two
    # together reads a load-shedding event as a broken client.
    ADMISSION = "admission"
    # A blanket exception handler wraps every upstream call, so it cannot know
    # which one raised. Attributing the failure to whichever stage happened to
    # run last would read as a defect in that stage.
    UNKNOWN = "unknown"


class RefinerRole(str, Enum):
    PRIMARY = "primary"
    CANDIDATE = "candidate"


class RefinementOutcomeCode(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED_LANGUAGE = "skipped_language"
    SKIPPED_OVERLOAD = "skipped_overload"
    SUBMISSION_FAILED = "submission_failed"


class MessageDirection(str, Enum):
    """Which side of the session spoke.

    Derived from the sending client's type rather than from the languages: a
    session where both participants share a language would otherwise be
    indistinguishable in either direction.
    """

    ADMIN_TO_CUSTOMER = "admin_to_customer"
    CUSTOMER_TO_ADMIN = "customer_to_admin"
    UNKNOWN = "unknown"


class InputMode(str, Enum):
    """Which pipeline ran. Audio adds an ASR stage that text never has."""

    AUDIO = "audio"
    TEXT = "text"
    UNKNOWN = "unknown"


class TerminalOutcome(str, Enum):
    """How the request ended, from the caller's point of view."""

    SUCCESS = "success"
    FAILURE = "failure"


class SessionLifecyclePhase(str, Enum):
    """The three points a session passes through.

    `terminated` is the funnel: it is the only one that knows how long the
    session lasted and how many messages it carried.
    """

    CREATED = "created"
    ACTIVATED = "activated"
    TERMINATED = "terminated"


class SessionTerminationReason(str, Enum):
    """Why a session ended, as a closed set.

    `SessionManager.terminate_session` takes `reason` as a free-form `str`, so
    without this the reason would be a free-text channel into a store that has
    no free-text kind. Every value the gateway actually passes has a member;
    anything else becomes `other`.
    """

    NONE = "none"
    MANUAL_ADMIN_TERMINATION = "manual_admin_termination"
    MANUAL_TERMINATION = "manual_termination"
    NEW_SESSION_CREATED = "new_session_created"
    SESSION_TIMEOUT = "session_timeout"
    SYSTEM_CLEANUP = "system_cleanup"
    OTHER = "other"

    @classmethod
    def classify(cls, raw: object) -> "SessionTerminationReason":
        """Never raise, and never store the value it was given."""
        try:
            reason = cls(raw)
        except (ValueError, TypeError):
            return cls.OTHER
        # `none` is the absence of a termination, not something a caller may
        # name -- a terminated session claiming `none` fails the invariant.
        return cls.OTHER if reason is cls.NONE else reason


class FeedbackAudience(str, Enum):
    """Who answered. Staff feedback must never pool with citizens' numbers."""

    GUEST = "guest"
    STAFF = "staff"
    INSTALLATION = "installation"


class FeedbackFormSource(str, Enum):
    STUDIO = "studio"
    BUNDLED = "bundled"


class FeedbackQuestionType(str, Enum):
    """The numeric question types. longText has no member: it is never emitted."""

    RATING = "rating"
    SCALE = "scale"


class AttributeKind(str, Enum):
    """What shape an allowlisted value may take.

    There is deliberately no free-text kind. Task 3.1 and 3.2 require every
    field to be a number, a closed enum, or an opaque reference, and the only
    way to enforce that is to make "arbitrary string" unrepresentable here.
    """

    UUID = "uuid"
    NUMBER = "number"
    ENUM = "enum"
    LABEL = "label"
    LANGUAGE = "language"
    OPAQUE_REF = "opaque_ref"
    TENANT_REF = "tenant_ref"


# A label is operator-set configuration (a model name, a release token), not
# user content: no whitespace, no punctuation that would let a sentence through.
# \Z, not $: `$` also matches immediately before a trailing newline, so a
# "no whitespace" guard was accepting "gpt-oss:20b\n". re.ASCII keeps \d from
# accepting Unicode decimal digits: "١٢٣" is not a number ClickHouse
# will parse into a UInt32 -- toUInt32OrZero turns it into a silent 0.
_LABEL_PATTERN: Final = re.compile(r"\A[A-Za-z0-9._:+/-]{1,64}\Z", re.ASCII)
_NUMBER_PATTERN: Final = re.compile(r"\A-?\d{1,19}\Z", re.ASCII)
_LANGUAGE_PATTERN: Final = re.compile(r"\A[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?\Z", re.ASCII)
_OPAQUE_REF_PATTERN: Final = re.compile(r"\A[0-9a-f]{16,64}\Z", re.ASCII)
_TENANT_REF_PATTERN: Final = re.compile(r"\A[0-9a-f]{12}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    kind: AttributeKind
    values: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if (self.kind is AttributeKind.ENUM) != bool(self.values):
            raise ValueError("exactly the ENUM kind declares a closed value set")


def _enum_values(enum_class: type[Enum]) -> frozenset[str]:
    return frozenset(str(member.value) for member in enum_class.__members__.values())


# The single manifest. Every key names its value shape, so widening the
# allowlist cannot smuggle in a free-text field by accident.
#
# event.name is deliberately absent: OTLP carries the event name as a top-level
# LogRecord field, which the exporter writes to its typed `EventName` column.
# See spike finding 9.1 in the design document.
ALLOWED_ATTRIBUTES: Final[Mapping[str, AttributeSpec]] = {
    "ssf.quality.event_id": AttributeSpec(AttributeKind.UUID),
    "ssf.quality.schema_version": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.refiner_role": AttributeSpec(AttributeKind.ENUM, _enum_values(RefinerRole)),
    "ssf.quality.model_ref": AttributeSpec(AttributeKind.LABEL),
    "ssf.quality.refinement_outcome": AttributeSpec(
        AttributeKind.ENUM, _enum_values(RefinementOutcomeCode)
    ),
    "ssf.quality.refinement_latency_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.refinement_changed": AttributeSpec(
        AttributeKind.ENUM, frozenset({"true", "false"})
    ),
    _SOURCE_LANG_ATTRIBUTE: AttributeSpec(AttributeKind.LANGUAGE),
    _TARGET_LANG_ATTRIBUTE: AttributeSpec(AttributeKind.LANGUAGE),
    _ERROR_CODE_ATTRIBUTE: AttributeSpec(AttributeKind.ENUM, _enum_values(QualityErrorCode)),
    _SESSION_REF_ATTRIBUTE: AttributeSpec(AttributeKind.OPAQUE_REF),
    _TENANT_REF_ATTRIBUTE: AttributeSpec(AttributeKind.TENANT_REF),
    # feedback_submitted (#304). The free text these ratings came with is in
    # the transactional store; there is deliberately no key for it here, and
    # AttributeKind has no member that could carry one.
    _FEEDBACK_REF_ATTRIBUTE: AttributeSpec(AttributeKind.OPAQUE_REF),
    "ssf.quality.translation_quality": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.performance": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.usability": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.net_promoter_score": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.feedback_form_version": AttributeSpec(AttributeKind.LABEL),
    _AUDIENCE_ATTRIBUTE: AttributeSpec(AttributeKind.ENUM, _enum_values(FeedbackAudience)),
    "ssf.quality.form_source": AttributeSpec(AttributeKind.ENUM, _enum_values(FeedbackFormSource)),
    "ssf.quality.feedback_locale": AttributeSpec(AttributeKind.LANGUAGE),
    "ssf.quality.answer_count": AttributeSpec(AttributeKind.NUMBER),
    # feedback_answer (PR 12). A question id is a Studio identifier, never the
    # question's wording, and fits a LABEL by Studio's own pattern.
    "ssf.quality.question_id": AttributeSpec(AttributeKind.LABEL),
    "ssf.quality.question_type": AttributeSpec(
        AttributeKind.ENUM, _enum_values(FeedbackQuestionType)
    ),
    "ssf.quality.answer_value": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.answer_min": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.answer_max": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.direction": AttributeSpec(AttributeKind.ENUM, _enum_values(MessageDirection)),
    "ssf.quality.input_mode": AttributeSpec(AttributeKind.ENUM, _enum_values(InputMode)),
    "ssf.quality.terminal_outcome": AttributeSpec(
        AttributeKind.ENUM, _enum_values(TerminalOutcome)
    ),
    "ssf.quality.failed_stage": AttributeSpec(AttributeKind.ENUM, _enum_values(PipelineStage)),
    "ssf.quality.total_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.asr_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.translation_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.refinement_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.tts_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.lifecycle_phase": AttributeSpec(
        AttributeKind.ENUM, _enum_values(SessionLifecyclePhase)
    ),
    "ssf.quality.termination_reason": AttributeSpec(
        AttributeKind.ENUM, _enum_values(SessionTerminationReason)
    ),
    "ssf.quality.session_duration_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.message_count": AttributeSpec(AttributeKind.NUMBER),
}

ALLOWED_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(ALLOWED_ATTRIBUTES)


class TelemetryMode(str, Enum):
    """DISABLED and PROBE keep exactly the meanings they shipped with.

    ENABLED is additive: it emits real pipeline events as well as the admin
    probe. PROBE therefore stays a pure transport check, so an operator can
    verify the pipeline without turning on production event volume, and
    nothing already deployed on `probe` changes behaviour on upgrade.
    """

    DISABLED = "disabled"
    PROBE = "probe"
    ENABLED = "enabled"

    @property
    def emits_pipeline_events(self) -> bool:
        return self is TelemetryMode.ENABLED

    @classmethod
    def parse(cls, raw: str | None) -> "TelemetryMode":
        """Never raise on operator input: an unknown mode falls back to disabled.

        A typo in SSF_QUALITY_TELEMETRY_MODE must not stop the gateway from
        serving translations. Telemetry is optional; the gateway is not.
        """
        try:
            return cls((raw or "").strip().lower())
        except ValueError:
            logger.warning(
                "Unknown quality telemetry mode %r; falling back to %s. Valid: %s",
                raw,
                cls.DISABLED.value,
                ", ".join(m.value for m in cls),
            )
            return cls.DISABLED


class ProbeOutcome(str, Enum):
    """The outcome of one emission. Doubles as the metric's `outcome` label."""

    DISABLED = "disabled"
    EMITTED = "emitted"
    DROPPED_DISALLOWED = "dropped_disallowed"
    EXPORT_FAILED = "export_failed"


class DisallowedTelemetryAttribute(ValueError):
    """Raised when an attribute key is not on the allowlist."""


class DisallowedTelemetryValue(ValueError):
    """Raised when an allowlisted key carries a value of the wrong shape.

    The key allowlist alone stops a *new* field leaking content; this stops an
    *existing* field being used as a smuggling channel -- an `error_code` set
    to a raw upstream message, say.
    """


@dataclass(frozen=True, slots=True)
class QualityProbeEvent:
    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: str

    def __post_init__(self) -> None:
        if self.emitted_at_utc.tzinfo is None:
            raise ValueError("emitted_at_utc must be timezone-aware UTC")
        if not self.event_type:
            raise ValueError("event_type must not be empty")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")


def _validate_envelope(emitted_at_utc: datetime, event_type: str, schema_version: int) -> None:
    if emitted_at_utc.tzinfo is None:
        raise ValueError("emitted_at_utc must be timezone-aware UTC")
    if not event_type:
        raise ValueError("event_type must not be empty")
    if schema_version < 1:
        raise ValueError("schema_version must be positive")


@dataclass(frozen=True, slots=True)
class RefinementAttemptEvent:
    """One LLM refinement attempt, primary or shadow candidate.

    Every field is a number or a closed enum except `model_ref`, which is an
    operator-set configuration token constrained to a label charset. Nothing
    here can express the text being refined, so this event carries no privacy
    risk by construction rather than by review.
    """

    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: QualityEventType
    refiner_role: RefinerRole
    model_ref: str
    outcome: RefinementOutcomeCode
    latency_ms: int
    changed: bool
    source_lang: str
    target_lang: str
    error_code: QualityErrorCode

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        if not _LABEL_PATTERN.match(self.model_ref):
            raise ValueError(f"model_ref is not a label token: {self.model_ref!r}")
        for code in (self.source_lang, self.target_lang):
            if not _LANGUAGE_PATTERN.match(code):
                raise ValueError(f"not a language code: {code!r}")

    def _attributes(self) -> dict[str, str]:
        return {
            "ssf.quality.refiner_role": self.refiner_role.value,
            "ssf.quality.model_ref": self.model_ref,
            "ssf.quality.refinement_outcome": self.outcome.value,
            "ssf.quality.refinement_latency_ms": str(self.latency_ms),
            "ssf.quality.refinement_changed": "true" if self.changed else "false",
            _SOURCE_LANG_ATTRIBUTE: self.source_lang,
            _TARGET_LANG_ATTRIBUTE: self.target_lang,
            _ERROR_CODE_ATTRIBUTE: self.error_code.value,
        }


@dataclass(frozen=True, slots=True)
class TranslationMessageEvent:
    """One processed message, successful or not.

    Deliberately narrow: this is the denominator every ratio in the dashboards
    divides by, so it has to be cheap enough to emit on every message and small
    enough to be obviously content-free. No field here is a LABEL -- the widest
    kind, and the only one a sentence fragment could fit through -- because
    nothing on a message row is operator-set configuration.

    ``session_ref`` is a keyed HMAC, never a session id and never the unkeyed
    digest the logs use. See session_pseudonym.py.
    """

    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: QualityEventType
    session_ref: str
    direction: MessageDirection
    input_mode: InputMode
    source_lang: str
    target_lang: str
    terminal_outcome: TerminalOutcome
    failed_stage: PipelineStage
    error_code: QualityErrorCode
    total_duration_ms: int
    asr_duration_ms: int
    translation_duration_ms: int
    refinement_duration_ms: int
    tts_duration_ms: int
    tenant_ref: str = MISSING_TENANT_REFERENCE

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        for name in _MESSAGE_DURATION_FIELDS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if not _OPAQUE_REF_PATTERN.match(self.session_ref):
            raise ValueError(_INVALID_SESSION_REF)
        if not _TENANT_REF_PATTERN.match(self.tenant_ref):
            raise ValueError(_INVALID_TENANT_REF)
        for code in (self.source_lang, self.target_lang):
            if not _LANGUAGE_PATTERN.match(code):
                raise ValueError(f"not a language code: {code!r}")
        # A half-filled row is worse than no row: it reads as a real outcome.
        # These pairs are the ones a partially populated recorder would get
        # wrong, and every dashboard panel keys off them.
        succeeded = self.terminal_outcome is TerminalOutcome.SUCCESS
        blamed = self.failed_stage is not PipelineStage.NONE
        explained = self.error_code is not QualityErrorCode.NONE
        if succeeded and (blamed or explained):
            raise ValueError("a successful message cannot name a failure")
        if not succeeded and not explained:
            raise ValueError("a failed message must carry an error code")

    def _attributes(self) -> dict[str, str]:
        return {
            _SESSION_REF_ATTRIBUTE: self.session_ref,
            _TENANT_REF_ATTRIBUTE: self.tenant_ref,
            "ssf.quality.direction": self.direction.value,
            "ssf.quality.input_mode": self.input_mode.value,
            _SOURCE_LANG_ATTRIBUTE: self.source_lang,
            _TARGET_LANG_ATTRIBUTE: self.target_lang,
            "ssf.quality.terminal_outcome": self.terminal_outcome.value,
            "ssf.quality.failed_stage": self.failed_stage.value,
            _ERROR_CODE_ATTRIBUTE: self.error_code.value,
            "ssf.quality.total_duration_ms": str(self.total_duration_ms),
            "ssf.quality.asr_duration_ms": str(self.asr_duration_ms),
            "ssf.quality.translation_duration_ms": str(self.translation_duration_ms),
            "ssf.quality.refinement_duration_ms": str(self.refinement_duration_ms),
            "ssf.quality.tts_duration_ms": str(self.tts_duration_ms),
        }


_MESSAGE_DURATION_FIELDS: Final[tuple[str, ...]] = (
    "total_duration_ms",
    "asr_duration_ms",
    "translation_duration_ms",
    "refinement_duration_ms",
    "tts_duration_ms",
)


@dataclass(frozen=True, slots=True)
class SessionLifecycleEvent:
    """One session transition. The denominator for every per-session ratio.

    Every field already exists on the `Session` dataclass; none of them is
    content. `message_count` is a count, not the messages, and
    `session_duration_ms` is derived from two timestamps the session already
    keeps.
    """

    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: QualityEventType
    session_ref: str
    phase: SessionLifecyclePhase
    termination_reason: SessionTerminationReason
    session_duration_ms: int
    message_count: int
    tenant_ref: str = MISSING_TENANT_REFERENCE

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        if self.session_duration_ms < 0:
            raise ValueError("session_duration_ms must not be negative")
        if self.message_count < 0:
            raise ValueError("message_count must not be negative")
        if not _OPAQUE_REF_PATTERN.match(self.session_ref):
            raise ValueError(_INVALID_SESSION_REF)
        if not _TENANT_REF_PATTERN.match(self.tenant_ref):
            raise ValueError(_INVALID_TENANT_REF)
        ended = self.phase is SessionLifecyclePhase.TERMINATED
        named = self.termination_reason is not SessionTerminationReason.NONE
        if ended != named:
            raise ValueError("exactly a terminated session carries a reason")

    def _attributes(self) -> dict[str, str]:
        return {
            _SESSION_REF_ATTRIBUTE: self.session_ref,
            _TENANT_REF_ATTRIBUTE: self.tenant_ref,
            "ssf.quality.lifecycle_phase": self.phase.value,
            "ssf.quality.termination_reason": self.termination_reason.value,
            "ssf.quality.session_duration_ms": str(self.session_duration_ms),
            "ssf.quality.message_count": str(self.message_count),
        }


_RATING_FIELDS: Final[tuple[str, ...]] = ("translation_quality", "performance", "usability")


@dataclass(frozen=True, slots=True)
class FeedbackSubmittedEvent:
    """One voluntary feedback submission, structured half only.

    `feedback_ref` is a keyed HMAC of the transactional record's id, so a row
    here can be tied to a stored submission by someone holding the key and to
    nothing at all by someone who is not. The free text that accompanied the
    answers is not representable in this class.

    The four ratings are the bundled form's, present only when the form asked
    those questions the bundled way. Silver stores an absent rating as 0, and
    gold averages only rows that carry them, so they are all four or none.
    """

    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: QualityEventType
    session_ref: str
    feedback_ref: str
    feedback_form_version: str
    audience: FeedbackAudience
    form_source: FeedbackFormSource
    feedback_locale: str
    answer_count: int
    translation_quality: int | None = None
    performance: int | None = None
    usability: int | None = None
    net_promoter_score: int | None = None
    tenant_ref: str = MISSING_TENANT_REFERENCE

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        if self.event_type is not QualityEventType.FEEDBACK_SUBMITTED:
            raise ValueError("event_type must be feedback_submitted")
        self._validate_ratings()
        if self.answer_count < 0:
            raise ValueError("answer_count must not be negative")
        if not _OPAQUE_REF_PATTERN.match(self.session_ref):
            raise ValueError(_INVALID_SESSION_REF)
        if not _OPAQUE_REF_PATTERN.match(self.feedback_ref):
            raise ValueError(_INVALID_FEEDBACK_REF)
        if not _TENANT_REF_PATTERN.match(self.tenant_ref):
            raise ValueError(_INVALID_TENANT_REF)
        if not _LABEL_PATTERN.match(self.feedback_form_version):
            raise ValueError("feedback_form_version is not a label")
        if not _LANGUAGE_PATTERN.match(self.feedback_locale):
            raise ValueError("feedback_locale is not a language code")

    @property
    def has_ratings(self) -> bool:
        return self.net_promoter_score is not None

    def _validate_ratings(self) -> None:
        ratings = [getattr(self, name) for name in _RATING_FIELDS]
        present = [value is not None for value in (*ratings, self.net_promoter_score)]
        if any(present) and not all(present):
            raise ValueError("the bundled ratings are all present or all absent")
        if not self.has_ratings:
            return
        for name, value in zip(_RATING_FIELDS, ratings):
            if not 1 <= value <= 5:
                raise ValueError(f"{name} must be between 1 and 5")
        if not 0 <= (self.net_promoter_score or 0) <= 10:
            raise ValueError("net_promoter_score must be between 0 and 10")

    def _attributes(self) -> dict[str, str]:
        attributes = {
            _SESSION_REF_ATTRIBUTE: self.session_ref,
            _TENANT_REF_ATTRIBUTE: self.tenant_ref,
            _FEEDBACK_REF_ATTRIBUTE: self.feedback_ref,
            "ssf.quality.feedback_form_version": self.feedback_form_version,
            _AUDIENCE_ATTRIBUTE: self.audience.value,
            "ssf.quality.form_source": self.form_source.value,
            "ssf.quality.feedback_locale": self.feedback_locale,
            "ssf.quality.answer_count": str(self.answer_count),
        }
        if self.has_ratings:
            attributes.update(
                {
                    "ssf.quality.translation_quality": str(self.translation_quality),
                    "ssf.quality.performance": str(self.performance),
                    "ssf.quality.usability": str(self.usability),
                    "ssf.quality.net_promoter_score": str(self.net_promoter_score),
                }
            )
        return attributes


# The silver columns are UInt8. Studio caps every range at 0-10 today.
_MAX_ANSWER_VALUE: Final[int] = 255


@dataclass(frozen=True, slots=True)
class FeedbackAnswerEvent:
    """One answered numeric question of a stored submission.

    The id is uuid5(submission event id, question id), so a re-emission by the
    reconciler lands on the same silver row and the same gold uniqExact entry.
    The question's wording is not representable here, only its Studio id.
    """

    event_id: UUID
    schema_version: int
    emitted_at_utc: datetime
    event_type: QualityEventType
    feedback_ref: str
    audience: FeedbackAudience
    question_id: str
    question_type: FeedbackQuestionType
    value: int
    minimum: int
    maximum: int
    tenant_ref: str = MISSING_TENANT_REFERENCE

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        if self.event_type is not QualityEventType.FEEDBACK_ANSWER:
            raise ValueError("event_type must be feedback_answer")
        if not 0 <= self.minimum < self.maximum <= _MAX_ANSWER_VALUE:
            raise ValueError("the answer range is not a valid range")
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("the answer lies outside its range")
        if not _LABEL_PATTERN.match(self.question_id):
            raise ValueError("question_id is not a label")
        if not _OPAQUE_REF_PATTERN.match(self.feedback_ref):
            raise ValueError(_INVALID_FEEDBACK_REF)
        if not _TENANT_REF_PATTERN.match(self.tenant_ref):
            raise ValueError(_INVALID_TENANT_REF)

    def _attributes(self) -> dict[str, str]:
        return {
            _TENANT_REF_ATTRIBUTE: self.tenant_ref,
            _FEEDBACK_REF_ATTRIBUTE: self.feedback_ref,
            _AUDIENCE_ATTRIBUTE: self.audience.value,
            "ssf.quality.question_id": self.question_id,
            "ssf.quality.question_type": self.question_type.value,
            "ssf.quality.answer_value": str(self.value),
            "ssf.quality.answer_min": str(self.minimum),
            "ssf.quality.answer_max": str(self.maximum),
        }


QualityEvent = (
    QualityProbeEvent
    | RefinementAttemptEvent
    | TranslationMessageEvent
    | SessionLifecycleEvent
    | FeedbackSubmittedEvent
    | FeedbackAnswerEvent
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What actually happened. `event_id` is None only when disabled."""

    outcome: ProbeOutcome
    event_id: UUID | None


def enforce_allowlist(attributes: Mapping[str, str]) -> None:
    """Fail closed: reject any key not explicitly permitted."""
    disallowed = sorted(set(attributes) - ALLOWED_ATTRIBUTE_KEYS)
    if disallowed:
        raise DisallowedTelemetryAttribute(f"disallowed attribute keys: {disallowed}")


_SHAPE_PATTERNS: Final[Mapping[AttributeKind, "re.Pattern[str]"]] = {
    AttributeKind.NUMBER: _NUMBER_PATTERN,
    AttributeKind.LABEL: _LABEL_PATTERN,
    AttributeKind.LANGUAGE: _LANGUAGE_PATTERN,
    AttributeKind.OPAQUE_REF: _OPAQUE_REF_PATTERN,
    AttributeKind.TENANT_REF: _TENANT_REF_PATTERN,
}


def _value_has_declared_shape(spec: AttributeSpec, value: str) -> bool:
    if spec.kind is AttributeKind.ENUM:
        return value in (spec.values or frozenset())
    if spec.kind is AttributeKind.UUID:
        try:
            UUID(value)
        except (ValueError, AttributeError, TypeError):
            return False
        return True
    return bool(_SHAPE_PATTERNS[spec.kind].match(value))


def enforce_value_shapes(attributes: Mapping[str, str]) -> None:
    """Fail closed on the value as well as the key.

    The rejection message names the key and its declared kind, never the value:
    a guard that echoes what it rejected would log the content it exists to
    keep out of the logs.
    """
    for key, value in attributes.items():
        spec = ALLOWED_ATTRIBUTES.get(key)
        if spec is None:
            raise DisallowedTelemetryAttribute(f"disallowed attribute key: {key!r}")
        if not isinstance(value, str) or not _value_has_declared_shape(spec, value):
            raise DisallowedTelemetryValue(
                f"{key!r} does not match its declared shape {spec.kind.value!r}"
            )


def to_otlp_attributes(event: QualityEvent) -> dict[str, str]:
    """Map a typed event onto OTel semantic-convention attribute keys."""
    attributes = {
        "ssf.quality.event_id": str(event.event_id),
        "ssf.quality.schema_version": str(event.schema_version),
    }
    per_event = getattr(event, "_attributes", None)
    if per_event is not None:
        attributes.update(per_event())
    enforce_allowlist(attributes)
    enforce_value_shapes(attributes)
    return attributes
