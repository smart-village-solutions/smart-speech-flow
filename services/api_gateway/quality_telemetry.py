"""Typed, allowlisted quality telemetry contract.

This module must never import the OTel SDK (that lives only in
quality_telemetry_otlp.py) and must never accept a dict from the pipeline: the
pipeline's debug_info carries source text, transcripts and raw errors, and must
not be reachable from here. See
openspec/changes/add-clickhouse-quality-telemetry/design.md.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final
from uuid import UUID, uuid4

from fastapi import Request
from prometheus_client import CollectorRegistry, Counter

logger = logging.getLogger(__name__)

SCHEMA_VERSION: Final[int] = 1


class QualityEventType(str, Enum):
    """The closed set of event types this pipeline knows how to store."""

    TELEMETRY_PROBE = "telemetry_probe"
    REFINEMENT_ATTEMPT = "refinement_attempt"
    TRANSLATION_MESSAGE = "translation_message"
    SESSION_LIFECYCLE = "session_lifecycle"


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
    AUDIO_VALIDATION_FAILED = "audio_validation_failed"
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


# A label is operator-set configuration (a model name, a release token), not
# user content: no whitespace, no punctuation that would let a sentence through.
# \Z, not $: `$` also matches immediately before a trailing newline, so a
# "no whitespace" guard was accepting "gpt-oss:20b\n". [0-9] and re.ASCII, not
# \d: \d accepts Unicode decimal digits, and "١٢٣" is not a number ClickHouse
# will parse into a UInt32 -- toUInt32OrZero turns it into a silent 0.
_LABEL_PATTERN: Final = re.compile(r"\A[A-Za-z0-9._:+/-]{1,64}\Z", re.ASCII)
_NUMBER_PATTERN: Final = re.compile(r"\A-?[0-9]{1,19}\Z", re.ASCII)
_LANGUAGE_PATTERN: Final = re.compile(
    r"\A[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?\Z", re.ASCII
)
_OPAQUE_REF_PATTERN: Final = re.compile(r"\A[0-9a-f]{16,64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    kind: AttributeKind
    values: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if (self.kind is AttributeKind.ENUM) != bool(self.values):
            raise ValueError("exactly the ENUM kind declares a closed value set")


def _enum_values(enum_class: type[Enum]) -> frozenset[str]:
    return frozenset(str(member.value) for member in enum_class)


# The single manifest. Every key names its value shape, so widening the
# allowlist cannot smuggle in a free-text field by accident.
#
# event.name is deliberately absent: OTLP carries the event name as a top-level
# LogRecord field, which the exporter writes to its typed `EventName` column.
# See spike finding 9.1 in the design document.
ALLOWED_ATTRIBUTES: Final[Mapping[str, AttributeSpec]] = {
    "ssf.quality.event_id": AttributeSpec(AttributeKind.UUID),
    "ssf.quality.schema_version": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.refiner_role": AttributeSpec(
        AttributeKind.ENUM, _enum_values(RefinerRole)
    ),
    "ssf.quality.model_ref": AttributeSpec(AttributeKind.LABEL),
    "ssf.quality.refinement_outcome": AttributeSpec(
        AttributeKind.ENUM, _enum_values(RefinementOutcomeCode)
    ),
    "ssf.quality.refinement_latency_ms": AttributeSpec(AttributeKind.NUMBER),
    "ssf.quality.refinement_changed": AttributeSpec(
        AttributeKind.ENUM, frozenset({"true", "false"})
    ),
    "ssf.quality.source_lang": AttributeSpec(AttributeKind.LANGUAGE),
    "ssf.quality.target_lang": AttributeSpec(AttributeKind.LANGUAGE),
    "ssf.quality.error_code": AttributeSpec(
        AttributeKind.ENUM, _enum_values(QualityErrorCode)
    ),
    "ssf.quality.session_ref": AttributeSpec(AttributeKind.OPAQUE_REF),
    "ssf.quality.direction": AttributeSpec(
        AttributeKind.ENUM, _enum_values(MessageDirection)
    ),
    "ssf.quality.input_mode": AttributeSpec(
        AttributeKind.ENUM, _enum_values(InputMode)
    ),
    "ssf.quality.terminal_outcome": AttributeSpec(
        AttributeKind.ENUM, _enum_values(TerminalOutcome)
    ),
    "ssf.quality.failed_stage": AttributeSpec(
        AttributeKind.ENUM, _enum_values(PipelineStage)
    ),
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


def _validate_envelope(
    emitted_at_utc: datetime, event_type: str, schema_version: int
) -> None:
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
            "ssf.quality.source_lang": self.source_lang,
            "ssf.quality.target_lang": self.target_lang,
            "ssf.quality.error_code": self.error_code.value,
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

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        for name in _MESSAGE_DURATION_FIELDS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if not _OPAQUE_REF_PATTERN.match(self.session_ref):
            raise ValueError("session_ref is not an opaque reference")
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
            "ssf.quality.session_ref": self.session_ref,
            "ssf.quality.direction": self.direction.value,
            "ssf.quality.input_mode": self.input_mode.value,
            "ssf.quality.source_lang": self.source_lang,
            "ssf.quality.target_lang": self.target_lang,
            "ssf.quality.terminal_outcome": self.terminal_outcome.value,
            "ssf.quality.failed_stage": self.failed_stage.value,
            "ssf.quality.error_code": self.error_code.value,
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

    def __post_init__(self) -> None:
        _validate_envelope(self.emitted_at_utc, self.event_type, self.schema_version)
        if self.session_duration_ms < 0:
            raise ValueError("session_duration_ms must not be negative")
        if self.message_count < 0:
            raise ValueError("message_count must not be negative")
        if not _OPAQUE_REF_PATTERN.match(self.session_ref):
            raise ValueError("session_ref is not an opaque reference")
        ended = self.phase is SessionLifecyclePhase.TERMINATED
        named = self.termination_reason is not SessionTerminationReason.NONE
        if ended != named:
            raise ValueError("exactly a terminated session carries a reason")

    def _attributes(self) -> dict[str, str]:
        return {
            "ssf.quality.session_ref": self.session_ref,
            "ssf.quality.lifecycle_phase": self.phase.value,
            "ssf.quality.termination_reason": self.termination_reason.value,
            "ssf.quality.session_duration_ms": str(self.session_duration_ms),
            "ssf.quality.message_count": str(self.message_count),
        }


QualityEvent = (
    QualityProbeEvent
    | RefinementAttemptEvent
    | TranslationMessageEvent
    | SessionLifecycleEvent
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
    the gateway's CollectorRegistry is a module-level object that outlives a
    single lifespan cycle: a test suite spins up many TestClient instances
    against the same app within one process, re-entering lifespan each time.
    prometheus_client raises on a second registration of the same metric name,
    so this mirrors app.py's own precedent of registering a series once and
    reusing it thereafter.

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
        "%s is not available on the gateway registry; telemetry counters "
        "will not be scraped",
        _EVENTS_COUNTER_NAME,
    )
    return Counter(
        _EVENTS_COUNTER_NAME,
        "Quality telemetry events by outcome",
        ["outcome"],
        registry=CollectorRegistry(),
    )


def discard_event(
    event_name: str, attributes: Mapping[str, str], emitted_at_utc: datetime
) -> None:
    """The exporter used in disabled mode.

    `emit_probe` returns before reaching it, so it exists only to keep the
    exporter argument non-optional: a nullable exporter would put the
    "is telemetry on?" test in two places.
    """


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
            logger.warning("Quality telemetry event rejected before export")
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
        total_duration_ms: int,
        asr_duration_ms: int,
        translation_duration_ms: int,
        refinement_duration_ms: int,
        tts_duration_ms: int,
    ) -> ProbeResult:
        """One processed message, successful or not.

        Gated on ENABLED for the same reason as the refinement event: PROBE
        stays a pure transport check. Every argument is coerced rather than
        trusted, because this is the row every ratio divides by and a dropped
        row makes each of those ratios wrong for as long as it is retained.
        """
        if not self._mode.emits_pipeline_events:
            return self._record(ProbeOutcome.DISABLED, None)

        try:
            event = TranslationMessageEvent(
                event_id=uuid4(),
                schema_version=SCHEMA_VERSION,
                emitted_at_utc=datetime.now(timezone.utc),
                event_type=QualityEventType.TRANSLATION_MESSAGE,
                session_ref=_as_opaque_ref(session_ref),
                direction=direction,
                input_mode=input_mode,
                source_lang=_as_language(source_lang),
                target_lang=_as_language(target_lang),
                terminal_outcome=terminal_outcome,
                failed_stage=failed_stage,
                error_code=error_code,
                total_duration_ms=max(0, int(total_duration_ms or 0)),
                asr_duration_ms=max(0, int(asr_duration_ms or 0)),
                translation_duration_ms=max(0, int(translation_duration_ms or 0)),
                refinement_duration_ms=max(0, int(refinement_duration_ms or 0)),
                tts_duration_ms=max(0, int(tts_duration_ms or 0)),
            )
        except (ValueError, TypeError):
            logger.warning("Quality telemetry event rejected before export")
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
                phase=phase,
                termination_reason=termination_reason,
                session_duration_ms=max(0, int(session_duration_ms or 0)),
                message_count=max(0, int(message_count or 0)),
            )
        except (ValueError, TypeError):
            logger.warning("Quality telemetry event rejected before export")
            return self._record(ProbeOutcome.DROPPED_DISALLOWED, None)

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


def get_quality_telemetry(request: Request) -> "QualityTelemetry":
    """FastAPI provider, following the app.state pattern used across app.py."""
    return request.app.state.quality_telemetry
