"""Supervisor routes of recording retention (spec §16, §16.1).

Extensions and legal holds are decisions the database applies, each with a
reason and an audit event; changes need a fresh MFA login (spec §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..clock import utc_now
from ..dependencies import optional_container
from ..recording.permissions import SUPERVISE, coded, require_permission, require_step_up
from ..recording.repository import RecordingStorageUnavailable
from ..recording.retention.decisions import (
    UNENDED_GRACE,
    ConversationSummary,
    DecisionKind,
    RetentionDecision,
    RetentionRefusedError,
    check_extension,
)
from ..recording.retention.decisions_repository import PostgresRetentionDecisions
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/admin/recording/conversations",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

Supervisor = Annotated[dict[str, Any], Depends(require_permission(SUPERVISE))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
_REFUSALS = {
    "no_conversation": (404, "CONVERSATION_NOT_FOUND"),
    "retention_not_extended": (409, "RETENTION_NOT_EXTENDED"),
    "retention_too_far": (422, "RETENTION_TOO_FAR"),
    "conversation_shredded": (409, "CONVERSATION_SHREDDED"),
}


def get_retention_decisions(request: Request) -> PostgresRetentionDecisions:
    service: PostgresRetentionDecisions | None = getattr(
        optional_container(request), "recording_retention", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Decisions = Annotated[PostgresRetentionDecisions, Depends(get_retention_decisions)]


class ExtensionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: AwareDatetime
    reason: str = Field(min_length=1, max_length=500)


class HoldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool
    reason: str = Field(min_length=1, max_length=500)


def _refused(error: RetentionRefusedError) -> Exception:
    status, code = _REFUSALS.get(error.code, (409, error.code.upper()))
    return coded(status, code, "The retention decision was refused")


def _unavailable() -> Exception:
    return coded(503, "RECORDING_UNAVAILABLE", "Recording storage unavailable")


async def _existing(
    decisions: PostgresRetentionDecisions, tenant_id: str, sub: str, conversation_id: uuid.UUID
) -> ConversationSummary:
    try:
        summary = await decisions.summary(tenant_id, str(conversation_id))
        if summary is None:
            await decisions.record_not_found(tenant_id, sub, str(conversation_id), utc_now())
    except RecordingStorageUnavailable:
        raise _unavailable() from None
    if summary is None:
        raise coded(404, "CONVERSATION_NOT_FOUND", "No such conversation")
    return summary


async def _decide(
    decisions: PostgresRetentionDecisions,
    decision: RetentionDecision,
    event_type: str,
) -> ConversationSummary:
    try:
        return await decisions.decide(decision, event_type)
    except RetentionRefusedError as error:
        raise _refused(error) from None
    except RecordingStorageUnavailable:
        raise _unavailable() from None


def _decision(
    context: StudioTenantContext,
    sub: str,
    conversation_id: uuid.UUID,
    kind: DecisionKind,
    reason: str,
    until: datetime | None = None,
) -> RetentionDecision:
    return RetentionDecision(
        tenant_id=context.tenant_id,
        decision_id=str(uuid.uuid4()),
        conversation_id=str(conversation_id),
        at=utc_now(),
        actor_sub=sub,
        kind=kind,
        retain_until=until,
        reason=reason,
    )


@router.get("")
async def list_conversations(
    context: TenantContext,
    claims: Supervisor,
    decisions: Decisions,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    started_before: AwareDatetime | None = None,
) -> dict[str, Any]:
    try:
        rows = await decisions.summaries(
            context.tenant_id, limit=limit, started_before=started_before
        )
    except RecordingStorageUnavailable:
        raise _unavailable() from None
    return {"conversations": [row.public() for row in rows]}


@router.get("/{conversation_id}")
async def one_conversation(
    conversation_id: uuid.UUID, context: TenantContext, claims: Supervisor, decisions: Decisions
) -> dict[str, Any]:
    return (await _existing(decisions, context.tenant_id, claims["sub"], conversation_id)).public()


@router.post("/{conversation_id}/retention", dependencies=[Depends(require_step_up)])
async def extend_retention(
    conversation_id: uuid.UUID,
    body: ExtensionBody,
    context: TenantContext,
    claims: Supervisor,
    decisions: Decisions,
) -> dict[str, Any]:
    current = await _existing(decisions, context.tenant_id, claims["sub"], conversation_id)
    try:
        check_extension(body.until, current.retention_until, utc_now())
    except RetentionRefusedError as error:
        raise _refused(error) from None
    decision = _decision(context, claims["sub"], conversation_id, "extend", body.reason, body.until)
    summary = await _decide(decisions, decision, "recording.retention.extended")
    return summary.public()


@router.post("/{conversation_id}/legal-hold", dependencies=[Depends(require_step_up)])
async def legal_hold(
    conversation_id: uuid.UUID,
    body: HoldBody,
    context: TenantContext,
    claims: Supervisor,
    decisions: Decisions,
) -> dict[str, Any]:
    await _existing(decisions, context.tenant_id, claims["sub"], conversation_id)
    kind: DecisionKind = "hold_on" if body.on else "hold_off"
    decision = _decision(context, claims["sub"], conversation_id, kind, body.reason)
    summary = await _decide(
        decisions, decision, f"recording.legal_hold.{'on' if body.on else 'off'}"
    )
    return {**summary.public(), "expires_now": not body.on and _due(summary, utc_now())}


def _due(summary: ConversationSummary, now: datetime) -> bool:
    """Past its date and over, as the primary worker shreds it in its next pass."""
    ended = summary.ended_at is not None or summary.started_at < now - UNENDED_GRACE
    return summary.retention_until <= now and ended
