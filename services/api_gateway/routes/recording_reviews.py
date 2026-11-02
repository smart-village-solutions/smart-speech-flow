"""A reviewer's inbox and review (spec §10.7).

These routes, the object route and integrity reports are the only ways a
reviewer reaches a conversation; `/archive/{id}` never serves them.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.permissions import REVIEW, require_permission
from ..recording.verification import VerificationError
from ..recording.verification_model import InboxRow, KeyRow, NotePost
from ..recording.verification_repository import ReviewOpened
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute
from .recording_archive import opened_body
from .recording_verifications import Service, record_body, refused

router = APIRouter(
    prefix="/api/admin/recording/reviews",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

Reviewer = Annotated[dict[str, Any], Depends(require_permission(REVIEW))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]


# 64 KiB of ciphertext plus its envelope, base64url without padding.
_NOTE_CHARACTERS = 87_428
_OVERALL_CHARACTERS = 43_731
MAX_NOTES = 5_000


class ReviewStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_head_seq: int = Field(ge=1)


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: uuid.UUID
    key_id: uuid.UUID
    ciphertext: str = Field(min_length=1, max_length=_NOTE_CHARACTERS)


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: str | None = Field(default=None, min_length=1, max_length=_OVERALL_CHARACTERS)
    notes: list[NoteBody] = Field(default_factory=list, max_length=MAX_NOTES)


class DecisionBody(DraftBody):
    outcome: Literal["approved", "not_approved"]
    signature: str = Field(min_length=86, max_length=86)


def decoded(body: DraftBody) -> tuple[bytes | None, tuple[NotePost, ...]]:
    try:
        overall = None if body.overall is None else from_b64url(body.overall)
        notes = tuple(
            NotePost(str(note.entry_id), str(note.key_id), from_b64url(note.ciphertext))
            for note in body.notes
        )
    except ValueError:
        raise refused(VerificationError("bad_notes")) from None
    return overall, notes


def _inbox_body(row: InboxRow) -> dict[str, Any]:
    return {
        "verification_id": row.verification_id,
        "status": row.status,
        "requested_at": row.requested_at.isoformat(),
        "requested_by": row.requested_by,
        "started_at": row.started_at.isoformat(),
        "ended_at": None if row.ended_at is None else row.ended_at.isoformat(),
        "messages": row.messages,
        "openable": row.openable,
        "requested_by_name": row.requested_by_name,
    }


def _key_body(key: KeyRow | None) -> dict[str, Any] | None:
    if key is None:
        return None
    return {
        "sub": key.sub,
        "key_version": key.key_version,
        "fingerprint": b64url(key.fingerprint),
        "enc_pub": b64url(key.enc_pub),
        "sig_pub": b64url(key.sig_pub),
    }


def review_body(opened: ReviewOpened) -> dict[str, Any]:
    record = opened.record
    return opened_body(opened.conversation) | {
        "review": {
            "record": record_body(record),
            "draft": {
                "overall": None if record.overall_note is None else b64url(record.overall_note),
                "notes": [
                    {
                        "entry_id": note.entry_id,
                        "key_id": note.key_id,
                        "ciphertext": b64url(note.ciphertext),
                    }
                    for note in opened.draft
                ],
            },
            "requester": _key_body(opened.requester),
            "requester_name": opened.requester_name,
        }
    }


@router.get("")
async def inbox(
    request: Request, context: TenantContext, claims: Reviewer, service: Service
) -> dict[str, Any]:
    try:
        rows = await service.inbox(
            context.tenant_id, claims["sub"], correlation_id_from_request(request)
        )
    except VerificationError as error:
        raise refused(error) from None
    return {"reviews": [_inbox_body(row) for row in rows]}


@router.get("/{verification_id}")
async def open_review(
    verification_id: uuid.UUID,
    request: Request,
    context: TenantContext,
    claims: Reviewer,
    service: Service,
) -> dict[str, Any]:
    try:
        opened = await service.open_review(
            context.tenant_id,
            claims["sub"],
            str(verification_id),
            correlation_id_from_request(request),
        )
    except VerificationError as error:
        raise refused(error) from None
    return review_body(opened)


@router.post("/{verification_id}/start")
async def start(
    verification_id: uuid.UUID,
    body: ReviewStartBody,
    request: Request,
    context: TenantContext,
    claims: Reviewer,
    service: Service,
) -> dict[str, Any]:
    try:
        row = await service.start(
            context.tenant_id,
            claims["sub"],
            str(verification_id),
            body.expected_head_seq,
            correlation_id_from_request(request),
        )
    except VerificationError as error:
        raise refused(error) from None
    return record_body(row)


@router.put("/{verification_id}/draft", status_code=204)
async def save_draft(
    verification_id: uuid.UUID,
    body: DraftBody,
    context: TenantContext,
    claims: Reviewer,
    service: Service,
) -> Response:
    overall, notes = decoded(body)
    try:
        await service.save_draft(
            context.tenant_id, claims["sub"], str(verification_id), overall, notes
        )
    except VerificationError as error:
        raise refused(error) from None
    return Response(status_code=204)


@router.post("/{verification_id}/decline", status_code=204)
async def decline(
    verification_id: uuid.UUID, context: TenantContext, claims: Reviewer, service: Service
) -> Response:
    try:
        await service.decline(context.tenant_id, claims["sub"], str(verification_id))
    except VerificationError as error:
        raise refused(error) from None
    return Response(status_code=204)


@router.post("/{verification_id}/decision")
async def decide(
    verification_id: uuid.UUID,
    body: DecisionBody,
    request: Request,
    context: TenantContext,
    claims: Reviewer,
    service: Service,
) -> dict[str, Any]:
    overall, notes = decoded(body)
    try:
        signature = from_b64url(body.signature)
    except ValueError:
        raise refused(VerificationError("signature_invalid")) from None
    try:
        row = await service.decide(
            context.tenant_id,
            claims["sub"],
            str(verification_id),
            body.outcome,
            overall,
            notes,
            signature,
            correlation_id_from_request(request),
        )
    except VerificationError as error:
        raise refused(error) from None
    return record_body(row) | {"outcome": row.outcome}
