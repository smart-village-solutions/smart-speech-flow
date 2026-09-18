"""The live, fail-closed authorisation for writing conversation content.

Every write of conversation content is preceded by its own Studio read. No
value is cached and no previous answer is reused: see
docs/superpowers/specs/2026-09-15-fail-closed-runtime-configuration-caching-design.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .consent import ConsentStatus
from .studio_runtime_client import StudioRuntimeClientError
from .studio_runtime_flow import RuntimeConfigurationFetcher
from .studio_runtime_token import StudioTokenError

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .runtime_policy_metrics import RuntimePolicyMetrics


class PolicyReason(str, Enum):
    """The low-cardinality reason label for one policy decision."""

    GRANTED = "granted"
    CONSENT_PENDING = "consent_pending"
    CONSENT_DECLINED = "consent_declined"
    POLICY_DISABLED = "policy_disabled"
    TENANT_UNAVAILABLE = "tenant_unavailable"
    STUDIO_UNAVAILABLE = "studio_unavailable"
    STUDIO_ERROR = "studio_error"
    VALIDATION_FAILED = "validation_failed"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The outcome of one live policy read."""

    authorized: bool
    reason: PolicyReason


# Keyed by code, never by the retryable flag: the same code can arrive with
# either value, and the label must not change with it.
_REASON_BY_CODE = {
    "tenant_suspended": PolicyReason.TENANT_UNAVAILABLE,
    "ssf_plugin_inactive": PolicyReason.TENANT_UNAVAILABLE,
    "ssf_tenant_not_ready": PolicyReason.TENANT_UNAVAILABLE,
    "runtime_configuration_unavailable": PolicyReason.STUDIO_UNAVAILABLE,
    "studio_runtime_network_error": PolicyReason.STUDIO_UNAVAILABLE,
    "studio_token_network_error": PolicyReason.STUDIO_UNAVAILABLE,
    "studio_runtime_response_invalid": PolicyReason.VALIDATION_FAILED,
    "studio_runtime_tenant_mismatch": PolicyReason.VALIDATION_FAILED,
    "studio_runtime_error_invalid": PolicyReason.VALIDATION_FAILED,
}

_CONSENT_REFUSALS = {
    ConsentStatus.DECLINED: PolicyReason.CONSENT_DECLINED,
    ConsentStatus.POLICY_DISABLED: PolicyReason.POLICY_DISABLED,
}


class RuntimePolicyGate:
    """Authorise one write of conversation content, or refuse it."""

    def __init__(
        self,
        client: RuntimeConfigurationFetcher,
        *,
        metrics: RuntimePolicyMetrics | None = None,
    ) -> None:
        self._client = client
        self._metrics = metrics

    async def authorize(
        self,
        tenant_id: str,
        consent_status: ConsentStatus,
        correlation_id: str,
    ) -> PolicyDecision:
        """Read the live policy and combine it with the session's consent."""
        started = time.perf_counter()
        decision = await self._decide(tenant_id, consent_status, correlation_id)
        if self._metrics is not None:
            self._metrics.record_decision(decision, time.perf_counter() - started)
            if not decision.authorized:
                self._metrics.record_discarded(decision.reason)
        return decision

    async def _decide(
        self,
        tenant_id: str,
        consent_status: ConsentStatus,
        correlation_id: str,
    ) -> PolicyDecision:
        try:
            configuration = await self._client.fetch(tenant_id, correlation_id)
        except (StudioRuntimeClientError, StudioTokenError) as error:
            reason = _REASON_BY_CODE.get(error.code, PolicyReason.STUDIO_ERROR)
            return PolicyDecision(False, reason)
        except Exception:  # noqa: BLE001 - any failure must refuse, never raise
            return PolicyDecision(False, PolicyReason.STUDIO_ERROR)

        if configuration.tenant.id != tenant_id:
            return PolicyDecision(False, PolicyReason.VALIDATION_FAILED)
        if configuration.conversation_content_storage.mode != "ask":
            return PolicyDecision(False, PolicyReason.POLICY_DISABLED)
        if consent_status is not ConsentStatus.GRANTED:
            reason = _CONSENT_REFUSALS.get(consent_status, PolicyReason.CONSENT_PENDING)
            return PolicyDecision(False, reason)
        return PolicyDecision(True, PolicyReason.GRANTED)


_GATE: RuntimePolicyGate | None = None


def bind_runtime_policy(gate: RuntimePolicyGate | None) -> None:
    """Bind the process-wide gate, or unbind it with `None`.

    Args:
        gate: The gate every write consults, or `None` to refuse every write.
    """
    global _GATE
    _GATE = gate


def current_runtime_policy() -> RuntimePolicyGate | None:
    """Return the bound gate. `None` means every write is refused."""
    return _GATE
