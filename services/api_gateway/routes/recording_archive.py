"""An employee's own archive: list, open, objects, amendments (spec §10.6).

Any holder of an `ssf.recording.*` permission may open what is wrapped for
them; the opening rule and its audit live in the service and the database.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.archive_access import ArchiveAccess, ArchiveAccessError
from ..recording.archive_access_repository import OpenedConversation
from ..recording.ceremony_repository import PostgresCeremonyRepository
from ..recording.crypto.encoding import b64url, from_b64url
from ..recording.permissions import (
    RECORDING_PERMISSIONS,
    SUPERVISE,
    coded,
    permissions_of,
    require_permission,
)
from ..recording.repository import RecordingStorageUnavailable
from ..recording.storage.archive import OBJECT_TYPES
from ..studio_runtime_flow import correlation_id_from_request
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..value_free_validation import ValueFreeValidationRoute
from .recording_generations import trust_body

router = APIRouter(
    prefix="/api/admin/recording/archive",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

RecordingUser = Annotated[dict[str, Any], Depends(require_permission(*RECORDING_PERMISSIONS))]
TenantContext = Annotated[StudioTenantContext, Depends(require_studio_tenant_context)]
# 32 KiB of ciphertext, base64url without padding.
_MAX_CIPHERTEXT_CHARACTERS = 43_691
_ANSWERS = {
    "not_found": (404, "CONVERSATION_NOT_FOUND"),
    "not_stored": (404, "OBJECT_NOT_STORED"),
    "key_not_usable": (409, "KEY_NOT_USABLE"),
    "entry_exists": (409, "ENTRY_EXISTS"),
    "bad_ciphertext": (422, "BAD_CIPHERTEXT"),
    "write_failed": (503, "ARCHIVE_WRITE_FAILED"),
    "unavailable": (503, "RECORDING_UNAVAILABLE"),
}


def get_archive_access(request: Request) -> ArchiveAccess:
    service: ArchiveAccess | None = getattr(
        optional_container(request), "recording_archive_access", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


def get_trust_source(request: Request) -> PostgresCeremonyRepository:
    repository: PostgresCeremonyRepository | None = getattr(
        optional_container(request), "recording_repository", None
    )
    if repository is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return repository


Access = Annotated[ArchiveAccess, Depends(get_archive_access)]
TrustSource = Annotated[PostgresCeremonyRepository, Depends(get_trust_source)]


class AmendmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: uuid.UUID
    key_id: uuid.UUID
    ciphertext: str = Field(min_length=1, max_length=_MAX_CIPHERTEXT_CHARACTERS)


class IntegrityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["trust", "wrap", "chain", "stamp", "object"]


def _answer(error: ArchiveAccessError) -> HTTPException:
    status, code = _ANSWERS.get(error.code, (503, "RECORDING_UNAVAILABLE"))
    detail: dict[str, Any] = {"error_code": code, "message": "The archive request was refused"}
    if error.code == "write_failed":
        # Committed to the chain but not spooled: the browser re-posts the same bytes.
        detail["committed"] = True
    return HTTPException(status_code=status, detail=detail)


def _supervisor(claims: dict[str, Any]) -> bool:
    """Opens conversations recovered through a completed request of the caller (§9.5)."""
    return SUPERVISE in permissions_of(claims)


def _time(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def opened_body(opened: OpenedConversation) -> dict[str, Any]:
    return {
        "conversation": {
            "conversation_id": opened.conversation_id,
            "employee_sub": opened.employee_sub,
            "legal_basis": opened.legal_basis,
            "started_at": opened.started_at.isoformat(),
            "ended_at": opened.ended_at.isoformat(),
            "retention_until": opened.retention_until.isoformat(),
            "legal_hold": opened.legal_hold,
            "incomplete": opened.incomplete,
            "verification": "not_verified",
        },
        "windows": [
            {
                "window_id": window.window_id,
                "opened_at": window.opened_at.isoformat(),
                "closed_at": _time(window.closed_at),
                "close_reason": window.close_reason,
                "pauses": list(window.pauses),
            }
            for window in opened.windows
        ],
        "entries": [
            {
                "seq": entry.seq,
                "entry_id": entry.entry_id,
                "kind": entry.kind,
                "window_id": entry.window_id,
                "key_id": entry.key_id,
                "objects": entry.objects,
                "prev_hash": b64url(entry.prev_hash),
                "hash": b64url(entry.hash),
                "signer_key_id": entry.signer_key_id,
                "signature": b64url(entry.signature),
                "created_at": entry.created_at.isoformat(),
                "stored_types": sorted(opened.stored.get(entry.entry_id, frozenset())),
            }
            for entry in opened.entries
        ],
        "stamps": [
            {
                "head_seq": stamp.head_seq,
                "head_hash": b64url(stamp.head_hash),
                "token": None if stamp.token is None else b64url(stamp.token),
            }
            for stamp in opened.stamps
        ],
        "keys": [
            {
                "key_id": key.key_id,
                "epoch": key.epoch,
                "recovery_wrapped": key.recovery_wrapped,
                "wrap": (
                    None
                    if key.wrap is None
                    else {
                        "blob": key.wrap.blob,
                        "creator_ref": key.wrap.creator_ref,
                        "creator_signature": b64url(key.wrap.creator_signature),
                    }
                ),
            }
            for key in opened.keys
        ],
    }


@router.get("")
async def list_own(
    request: Request,
    context: TenantContext,
    claims: RecordingUser,
    access: Access,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    started_before: AwareDatetime | None = None,
    before_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Newest first; the next page passes the last row's `started_at` and `conversation_id`."""
    try:
        rows = await access.conversations(
            context.tenant_id,
            claims["sub"],
            limit=limit,
            started_before=started_before,
            before_id=None if before_id is None else str(before_id),
            supervisor=_supervisor(claims),
        )
    except ArchiveAccessError as error:
        raise _answer(error) from None
    sub = claims["sub"]
    names = await access.employee_names(
        context.tenant_id, sub, rows, correlation_id_from_request(request)
    )
    return {
        "conversations": [
            row.public(sub) | {"employee_name": names.get(row.employee_sub)} for row in rows
        ]
    }


@router.get("/trust")
async def trust(
    context: TenantContext, claims: RecordingUser, source: TrustSource
) -> dict[str, Any]:
    try:
        key = await source.active_recovery_key(context.tenant_id)
        chain = [] if key is None else await source.chain(context.tenant_id, key.key_id)
    except RecordingStorageUnavailable:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording storage unavailable") from None
    if key is None or not chain:
        raise coded(404, "RECOVERY_KEY_MISSING", "No active recovery key")
    return trust_body(key, chain)


@router.get("/{conversation_id}")
async def open_one(
    conversation_id: uuid.UUID, context: TenantContext, claims: RecordingUser, access: Access
) -> dict[str, Any]:
    try:
        opened = await access.open(
            context.tenant_id, claims["sub"], str(conversation_id), supervisor=_supervisor(claims)
        )
    except ArchiveAccessError as error:
        raise _answer(error) from None
    return opened_body(opened)


@router.get("/{conversation_id}/objects/{entry_id}/{object_type}")
async def one_object(
    conversation_id: uuid.UUID,
    entry_id: uuid.UUID,
    object_type: str,
    context: TenantContext,
    claims: RecordingUser,
    access: Access,
) -> Response:
    if object_type not in OBJECT_TYPES:
        raise _answer(ArchiveAccessError("not_found"))
    try:
        data = await access.object(
            context.tenant_id,
            claims["sub"],
            str(conversation_id),
            str(entry_id),
            object_type,
            supervisor=_supervisor(claims),
        )
    except ArchiveAccessError as error:
        raise _answer(error) from None
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{conversation_id}/amendments", status_code=201)
async def amend(
    conversation_id: uuid.UUID,
    body: AmendmentBody,
    response: Response,
    context: TenantContext,
    claims: RecordingUser,
    access: Access,
) -> dict[str, Any]:
    """201 for a new entry; 200 when the same bytes were posted under that entry before."""
    try:
        ciphertext = from_b64url(body.ciphertext)
    except ValueError:
        raise _answer(ArchiveAccessError("bad_ciphertext")) from None
    try:
        entry, created = await access.amend(
            context.tenant_id,
            claims["sub"],
            str(conversation_id),
            str(body.entry_id),
            str(body.key_id),
            ciphertext,
        )
    except ArchiveAccessError as error:
        raise _answer(error) from None
    if not created:
        response.status_code = 200
    return {"entry_id": entry.entry_id, "seq": entry.seq}


@router.post("/{conversation_id}/integrity-failures", status_code=204)
async def integrity_failure(
    conversation_id: uuid.UUID,
    body: IntegrityBody,
    context: TenantContext,
    claims: RecordingUser,
    access: Access,
) -> Response:
    try:
        await access.report(
            context.tenant_id,
            claims["sub"],
            str(conversation_id),
            body.stage,
            supervisor=_supervisor(claims),
        )
    except ArchiveAccessError as error:
        raise _answer(error) from None
    return Response(status_code=204)
