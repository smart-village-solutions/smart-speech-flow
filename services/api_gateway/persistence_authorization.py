"""Authorise one message's artefacts, each with its own live Studio read.

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
    """Run one live read per artefact that exists, refusing on any failure.

    Args:
        gate: The bound policy gate, or `None` when none is bound.
        tenant_id: The tenant the conversation belongs to.
        consent_status: The session's resolved consent.
        correlation_id: The correlation ID of the request being served.
        has_original_audio: Whether the guest's input audio was stored.
        has_translated_audio: Whether synthesised audio was stored.

    Returns:
        One decision per artefact, refused whenever no gate is bound.
    """
    if gate is None:
        return ArtifactAuthorization(False, False, False)

    async def decide() -> bool:
        decision = await gate.authorize(tenant_id, consent_status, correlation_id)
        return decision.authorized

    record = await decide()
    original = await decide() if has_original_audio else False
    translated = await decide() if has_translated_audio else False
    return ArtifactAuthorization(record, original, translated)
