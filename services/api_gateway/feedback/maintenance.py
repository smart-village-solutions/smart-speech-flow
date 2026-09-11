"""Analytics recovery and retention enforcement (#305).

Two passes, both driven by a lifespan task in every replica:

* **Reconciliation** re-emits submissions whose analytics event never reached
  the pipeline, using the `analytics_event_id` stored on the row. Silver's
  ReplacingMergeTree and gold's `uniqExactState(event_id)` deduplicate on that
  id, so a re-emission cannot inflate counts.
* **Retention** deletes rows past `expires_at` and writes a content-free audit
  in the same transaction.

Neither pass raises. A maintenance failure must show up as a metric, never as
an exception that kills the lifespan task and silently stops all future passes.

Free text is structurally out of reach here: `PendingAnalytics` has no
ciphertext field and the claim query does not select the column.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from prometheus_client import CollectorRegistry, Counter, Gauge

from ..quality_telemetry import ProbeOutcome
from ..session_pseudonym import feedback_ref
from .models import AnalyticsState
from .repository import RetentionLockUnavailable

logger = logging.getLogger(__name__)

RECONCILIATION_BATCH_LIMIT = 200
RETENTION_BATCH_LIMIT = 500

# A fixed key for pg_try_advisory_xact_lock. Arbitrary but stable: every
# replica must derive the same number or the lock protects nothing.
RETENTION_LOCK_KEY = 0x55F_FEED


@dataclass(frozen=True, slots=True)
class ReconciliationPass:
    recovered: int = 0
    failed: int = 0
    drained: int = 0
    unavailable: bool = False


@dataclass(frozen=True, slots=True)
class RetentionPass:
    deleted: int = 0
    skipped: bool = False
    failed: bool = False


def _register(build: Callable[[], Any], registry: CollectorRegistry, name: str) -> Any:
    """Register a metric once per registry, reusing it on repeat calls.

    The lifespan re-enters on every TestClient in a test process while the
    gateway's registry outlives it, and prometheus_client raises on a duplicate
    name. Mirrors quality_telemetry._events_counter, including its rule that
    every path out of here ends in a usable metric: observability must not be
    able to stop the gateway from starting.
    """
    try:
        return build()
    except ValueError:
        pass

    existing = getattr(registry, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing

    logger.warning("%s is not available on the gateway registry", name)
    return None


class FeedbackMaintenanceMetrics:
    """Counters for the two passes, on the gateway's own registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.reconciliation = _register(
            lambda: Counter(
                "ssf_feedback_reconciliation_total",
                "Feedback analytics reconciliation attempts by outcome",
                ["outcome"],
                registry=registry,
            ),
            registry,
            "ssf_feedback_reconciliation_total",
        )
        # A gauge, not a counter: the number has to fall when the backlog drains.
        self.backlog = _register(
            lambda: Gauge(
                "ssf_feedback_reconciliation_backlog",
                "Feedback rows awaiting analytics delivery at the last pass",
                registry=registry,
            ),
            registry,
            "ssf_feedback_reconciliation_backlog",
        )
        self.deleted = _register(
            lambda: Counter(
                "ssf_feedback_retention_deleted_total",
                "Feedback rows deleted at their retention expiry",
                registry=registry,
            ),
            registry,
            "ssf_feedback_retention_deleted_total",
        )
        self.failures = _register(
            lambda: Counter(
                "ssf_feedback_maintenance_failures_total",
                "Feedback maintenance passes that could not complete",
                ["job"],
                registry=registry,
            ),
            registry,
            "ssf_feedback_maintenance_failures_total",
        )

    def _count(self, metric: Any, amount: float = 1.0, **labels: str) -> None:
        if metric is None or amount <= 0:
            return
        (metric.labels(**labels) if labels else metric).inc(amount)

    def recovered(self, count: int) -> None:
        self._count(self.reconciliation, count, outcome="recovered")

    def failed(self, count: int) -> None:
        self._count(self.reconciliation, count, outcome="failed")

    def drained(self, count: int) -> None:
        self._count(self.reconciliation, count, outcome="not_applicable")

    def observed_backlog(self, depth: int) -> None:
        if self.backlog is not None:
            self.backlog.set(depth)

    def deleted_rows(self, count: int) -> None:
        self._count(self.deleted, count)

    def job_failed(self, job: str) -> None:
        self._count(self.failures, 1, job=job)


class FeedbackMaintenance:
    def __init__(
        self,
        *,
        repository: Any,
        telemetry: Any,
        metrics: FeedbackMaintenanceMetrics,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        reconciliation_limit: int = RECONCILIATION_BATCH_LIMIT,
        retention_limit: int = RETENTION_BATCH_LIMIT,
    ) -> None:
        self._repository = repository
        self._telemetry = telemetry
        self._metrics = metrics
        self._clock = clock
        self._reconciliation_limit = reconciliation_limit
        self._retention_limit = retention_limit

    async def reconcile_once(self) -> ReconciliationPass:
        try:
            pending = await self._repository.claim_pending_analytics(self._reconciliation_limit)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            logger.warning("Feedback reconciliation could not read: %s", type(error).__name__)
            self._metrics.job_failed("reconciliation")
            return ReconciliationPass(unavailable=True)

        self._metrics.observed_backlog(len(pending))

        recovered = failed = drained = 0
        for row in pending:
            outcome = await self._redeliver(row)
            if outcome is ProbeOutcome.EMITTED:
                recovered += 1
            elif outcome is ProbeOutcome.DISABLED:
                drained += 1
            else:
                failed += 1

        self._metrics.recovered(recovered)
        self._metrics.failed(failed)
        self._metrics.drained(drained)
        return ReconciliationPass(recovered=recovered, failed=failed, drained=drained)

    async def _redeliver(self, row: Any) -> ProbeOutcome:
        """One row. Returns the outcome; never raises."""
        try:
            result = self._telemetry.emit_feedback_submitted(
                event_id=row.analytics_event_id,
                session_ref=row.session_ref,
                feedback_ref=feedback_ref(row.feedback_id),
                translation_quality=row.translation_quality,
                performance=row.performance,
                usability=row.usability,
                net_promoter_score=row.net_promoter_score,
                form_version=row.form_version,
            )
        except Exception as error:  # noqa: BLE001 - one bad row must not end the batch
            logger.warning("Feedback re-emission raised: %s", type(error).__name__)
            return ProbeOutcome.EXPORT_FAILED

        try:
            if result.outcome is ProbeOutcome.EMITTED:
                await self._repository.mark_analytics_delivered(row.feedback_id, row.tenant_id)
            elif result.outcome is ProbeOutcome.DISABLED:
                await self._repository.mark_analytics_state(
                    row.feedback_id, AnalyticsState.NOT_APPLICABLE, row.tenant_id
                )
        except Exception as error:  # noqa: BLE001
            # The event went out but the row still says pending. The next pass
            # re-emits the same id, which gold deduplicates, so this is safe.
            logger.warning("Feedback state update failed: %s", type(error).__name__)
            return ProbeOutcome.EXPORT_FAILED

        return result.outcome

    async def expire_once(self) -> RetentionPass:
        try:
            deleted = await self._repository.delete_expired(
                self._clock(), self._retention_limit, RETENTION_LOCK_KEY
            )
        except RetentionLockUnavailable:
            # Normal with more than one replica: exactly one wins each pass.
            return RetentionPass(skipped=True)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            logger.warning("Feedback retention pass failed: %s", type(error).__name__)
            self._metrics.job_failed("retention")
            return RetentionPass(failed=True)

        self._metrics.deleted_rows(len(deleted))
        return RetentionPass(deleted=len(deleted))
