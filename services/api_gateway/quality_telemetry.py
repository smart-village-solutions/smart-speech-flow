"""Typed, allowlisted quality telemetry contract.

This module must never import the OTel SDK (that lives only in
quality_telemetry_otlp.py) and must never accept a dict from the pipeline: the
pipeline's debug_info carries source text, transcripts and raw errors, and must
not be reachable from here. See
openspec/changes/add-clickhouse-quality-telemetry/design.md.
"""

from __future__ import annotations

import logging
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

# event.name is deliberately absent: OTLP carries the event name as a top-level
# LogRecord field, which the exporter writes to its typed `EventName` column.
# See spike finding 9.1 in the design document.
ALLOWED_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "ssf.quality.event_id",
        "ssf.quality.schema_version",
    }
)


class TelemetryMode(str, Enum):
    DISABLED = "disabled"
    PROBE = "probe"

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


def to_otlp_attributes(event: QualityProbeEvent) -> dict[str, str]:
    """Map a typed event onto OTel semantic-convention attribute keys."""
    attributes = {
        "ssf.quality.event_id": str(event.event_id),
        "ssf.quality.schema_version": str(event.schema_version),
    }
    enforce_allowlist(attributes)
    return attributes


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
    """
    existing = registry._names_to_collectors.get(_EVENTS_COUNTER_NAME)
    if isinstance(existing, Counter):
        return existing
    return Counter(
        _EVENTS_COUNTER_NAME,
        "Quality telemetry events by outcome",
        ["outcome"],
        registry=registry,
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

        event = QualityProbeEvent(
            event_id=uuid4(),
            schema_version=SCHEMA_VERSION,
            emitted_at_utc=datetime.now(timezone.utc),
            event_type=event_type,
        )

        try:
            self._exporter(
                event.event_type, to_otlp_attributes(event), event.emitted_at_utc
            )
        except DisallowedTelemetryAttribute:
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
