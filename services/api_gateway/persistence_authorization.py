"""Authorise every artefact of one message with one live Studio read.

Called after the participant-visible result has been produced, never before:
see docs/superpowers/specs/2026-09-17-consent-gated-persistence-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from .consent import ConsentStatus
from .runtime_policy import RuntimePolicyGate


@dataclass(frozen=True, slots=True)
class ArtifactAuthorization:
    """Whether each artefact of one message may be retained."""

    record: bool
    original_audio: bool
    translated_audio: bool


async def authorize_message_artifacts(
    *,
    gate: RuntimePolicyGate | None,
    tenant_id: str,
    consent_status: ConsentStatus,
    correlation_id: str,
    has_original_audio: bool,
    has_translated_audio: bool,
) -> ArtifactAuthorization:
    """Decide every artefact of one message with one live read, refusing on any failure.

    The read is not retried: a refusal stands for the whole message, so its
    artefacts never get split decisions.

    Args:
        gate: The bound policy gate, or `None` when none is bound.
        tenant_id: The tenant the conversation belongs to.
        consent_status: The session's resolved consent.
        correlation_id: The correlation ID of the request being served.
        has_original_audio: Whether the guest's input audio was stored.
        has_translated_audio: Whether synthesised audio was stored.

    Returns:
        The read's decision for each artefact that exists, refused whenever no
        gate is bound.
    """
    if gate is None:
        return ArtifactAuthorization(False, False, False)
    decision = await gate.authorize(tenant_id, consent_status, correlation_id)
    authorized = decision.authorized
    return ArtifactAuthorization(
        record=authorized,
        original_audio=authorized and has_original_audio,
        translated_audio=authorized and has_translated_audio,
    )
