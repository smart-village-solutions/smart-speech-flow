"""Counts every live Studio policy read, by the stage that made it.

A failed read refuses whatever waited on it: a staff session is not created,
consent cannot be granted at activation, and a message's content is not
stored. Every label is a fixed vocabulary; no tenant or session becomes one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from prometheus_client import CollectorRegistry, Counter, Gauge

from .studio_runtime_v2_client import TENANT_CONFLICT_CODES
from .studio_v2 import RuntimeRead

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .studio_runtime_flow import RuntimeConfigurationFetcher

PolicyReadStage = Literal["session_create", "activation", "message"]
PolicyReadOutcome = Literal["ok", "unavailable", "contract_error", "tenant_conflict"]
STAGES: tuple[PolicyReadStage, ...] = ("session_create", "activation", "message")
OUTCOMES: tuple[PolicyReadOutcome, ...] = ("ok", "unavailable", "contract_error", "tenant_conflict")

_UNAVAILABLE_CODES = frozenset(
    {
        "runtime_configuration_unavailable",
        "studio_runtime_network_error",
        "studio_token_network_error",
    }
)


def read_outcome(error: Exception) -> PolicyReadOutcome:
    """The outcome label of a failed read; anything unrecognised is a contract error.

    A 5xx means Studio, or a proxy in front of it, did not answer, whatever the
    code: a proxy's HTML error page has no JSON, so it arrives as
    `studio_runtime_response_invalid`. A 429 is Studio asking to come back
    later, not an answer outside the contract. The token client carries no
    status and sets `retryable` exactly when its endpoint answered 5xx.
    """
    code = getattr(error, "code", None)
    if not isinstance(code, str):
        return "contract_error"
    if code in TENANT_CONFLICT_CODES:
        return "tenant_conflict"
    status = getattr(error, "status", None)
    if code in _UNAVAILABLE_CODES or (isinstance(status, int) and (status >= 500 or status == 429)):
        return "unavailable"
    if code == "studio_token_authentication_failed" and getattr(error, "retryable", False):
        return "unavailable"
    return "contract_error"


class StudioPolicyReadMetrics:
    """One app's policy read series, registered once per app registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._reads = Counter(
            "ssf_studio_policy_read_total",
            "Live Studio policy reads, by the stage that made them and their outcome",
            ("stage", "outcome"),
            registry=registry,
        )
        # Without a runtime client no read ever happens, so the counter alone
        # would stay silent while every decision is refused.
        self._gate_bound = Gauge(
            "ssf_studio_policy_gate_bound",
            "1 while the gateway can read the Studio policy, "
            "0 while every policy decision is refused unread",
            registry=registry,
        )
        # Present from the first scrape, so increase() has a prior sample.
        for stage in STAGES:
            for outcome in OUTCOMES:
                self._reads.labels(stage=stage, outcome=outcome)

    def record(self, stage: PolicyReadStage, outcome: PolicyReadOutcome) -> None:
        self._reads.labels(stage=stage, outcome=outcome).inc()

    def gate_bound(self, bound: bool) -> None:
        self._gate_bound.set(1 if bound else 0)


class CountedPolicyReads:
    """A runtime fetcher that counts each read under one stage."""

    def __init__(
        self,
        inner: RuntimeConfigurationFetcher,
        metrics: StudioPolicyReadMetrics,
        stage: PolicyReadStage,
    ) -> None:
        self._inner = inner
        self._metrics = metrics
        self._stage = stage

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        try:
            read = await self._inner.fetch(tenant_id, correlation_id)
        except Exception as error:
            self._metrics.record(self._stage, read_outcome(error))
            raise
        self._metrics.record(self._stage, "ok")
        return read
