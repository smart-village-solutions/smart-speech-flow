"""Locked reads and the writes several recovery steps share (spec §9.5, §9.6).

Every write locks the request row first and applies a due expiry or an empty
scope before anything else, so a step can never land on a request that has
already lapsed. A refusal that must be recorded is returned as `Refused`, so
its transaction commits too.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import asyncpg

from .audit import AuditEvent
from .crypto.encoding import b64url
from .crypto.signatures import partial_hash
from .recovery_requests_model import (
    REQUEST_LIFETIME,
    SYSTEM_ACTOR,
    Approval,
    ApproverScopeKey,
    DecisionRow,
    NewRequest,
    NewWrap,
    Refused,
    RequestRow,
    ScopeKey,
    ServedApproval,
    ServedPartials,
    ServedWrap,
    UnrecoverableKey,
    WrapVerifier,
)
from .recovery_requests_sql import (
    FILING_CHECK,
    HOLDER,
    LATEST_DECISION,
    LISTED_HOLDER,
    OPEN_KEY_RECOVERY,
    REMAINING_LOCKED,
    REQUESTER_KEY,
    VALID_APPROVALS,
    decision_row,
    replaced,
    request_row,
    scope_of,
    signed_partials,
)
from .repository import append_audit, append_audits


async def close_request(
    connection: asyncpg.Connection,
    tenant_id: str,
    request_id: str,
    status: str,
    actor: str,
    now: datetime,
    before: Sequence[AuditEvent] = (),
) -> None:
    """Closes an open request and deletes its partials; `before` is audited ahead of the close."""
    await connection.execute(
        "UPDATE recovery_requests SET status = $2, closed_at = $3"
        " WHERE request_id = $1 AND status = 'open'",
        request_id,
        status,
        now,
    )
    await connection.execute("DELETE FROM recovery_partials WHERE request_id = $1", request_id)
    event = f"recovery.request.{status}"
    await append_audits(connection, [*before, AuditEvent(tenant_id, actor, event, request_id, now)])


async def lock_request(
    connection: asyncpg.Connection, tenant_id: str, request_id: str, now: datetime
) -> tuple[RequestRow, tuple[ScopeKey, ...]] | None:
    """The request under lock, closed first if it lapsed or lost its scope; None if unknown."""
    row = await connection.fetchrow(
        "SELECT * FROM recovery_requests WHERE request_id = $1 FOR UPDATE", request_id
    )
    if row is None:
        return None
    request = request_row(row)
    if request.status != "open":
        return request, ()
    if request.expires_at <= now:
        await close_request(connection, tenant_id, request_id, "expired", SYSTEM_ACTOR, now)
        return replaced(request, "expired", now), ()
    remaining = scope_of(await connection.fetch(REMAINING_LOCKED, request_id, now))
    if not remaining:
        await close_request(connection, tenant_id, request_id, "scope_gone", SYSTEM_ACTOR, now)
        return replaced(request, "scope_gone", now), ()
    return request, remaining


async def own_request(
    connection: asyncpg.Connection,
    tenant_id: str,
    sub: str,
    request_id: str,
    now: datetime,
    may_supervise: bool,
) -> Refused | tuple[RequestRow, tuple[ScopeKey, ...]]:
    """The caller's own request under lock; another's reads as unknown.

    An access request needs `supervise` at the time of the call, checked here
    under the lock and before any write or audit of the step (§9.6).
    """
    row = await connection.fetchrow(
        "SELECT requester_sub, kind FROM recovery_requests WHERE request_id = $1 FOR UPDATE",
        request_id,
    )
    if row is None or row["requester_sub"] != sub:
        return await not_found(connection, tenant_id, sub, request_id, now)
    # Before lock_request may close a lapsed request, which is a write and an audit.
    if row["kind"] == "access" and not may_supervise:
        return Refused("forbidden")
    locked = await lock_request(connection, tenant_id, request_id, now)
    if locked is None:  # cannot happen: this transaction holds the row
        return await not_found(connection, tenant_id, sub, request_id, now)
    return locked


async def requester_key(connection: asyncpg.Connection, sub: str) -> int | None:
    """Taken before the request lock: the order of the re-enrolment swap (§9.6)."""
    version: int | None = await connection.fetchval(REQUESTER_KEY, sub)
    return version


async def not_found(
    connection: asyncpg.Connection, tenant_id: str, sub: str, request_id: str, now: datetime
) -> Refused:
    await append_audit(
        connection, AuditEvent(tenant_id, sub, "recovery.request.not_found", request_id, now)
    )
    return Refused("not_found")


async def next_attempt(
    connection: asyncpg.Connection, request_id: str, holder_index: int
) -> int | None:
    """1 for a first decision; the next number after a rejected approval; else None."""
    latest = await connection.fetchrow(LATEST_DECISION, request_id, holder_index)
    if latest is None:
        return 1
    if latest["decision"] == "approved" and latest["rejected"]:
        return int(latest["attempt"]) + 1
    return None


async def decidable_by(
    connection: asyncpg.Connection, tenant_id: str, sub: str, request_id: str, now: datetime
) -> Refused | tuple[Any, int, RequestRow, tuple[ScopeKey, ...]]:
    """The one path of the eligibility rules: detail, approval and decline all use it."""
    # Shared before the request, as filing does: a swap or a leaver's retirement holds it
    # exclusively, so a decision either commits first or sees the share stale (§9.8).
    await connection.execute(REQUESTER_KEY, sub)
    locked = await lock_request(connection, tenant_id, request_id, now)
    if locked is None:
        return await not_found(connection, tenant_id, sub, request_id, now)
    request, remaining = locked
    # The requester can see the request, so they learn why, share or not.
    if request.requester_sub == sub:
        await append_audit(
            connection, AuditEvent(tenant_id, sub, "recovery.approval.refused", request_id, now)
        )
        return Refused("requester_cannot_approve")
    # A holder of the request's generation learns that it closed, though its share may be gone.
    if not await connection.fetchval(LISTED_HOLDER, request.holders_ceremony_id, sub):
        return await not_found(connection, tenant_id, sub, request_id, now)
    if request.status != "open":
        return Refused("closed")
    holder = await connection.fetchrow(HOLDER, request.recovery_key_id, sub)
    if holder is None:
        return await not_found(connection, tenant_id, sub, request_id, now)
    if not holder["fresh"]:
        return Refused("share_stale")
    attempt = await next_attempt(connection, request_id, holder["holder_index"])
    if attempt is None:
        return Refused("already_decided")
    return holder, attempt, request, remaining


async def approver_keys(
    connection: asyncpg.Connection, remaining: tuple[ScopeKey, ...], recovery_key_id: str
) -> tuple[ApproverScopeKey, ...]:
    rows = await connection.fetch(
        "SELECT k.conversation_id, k.key_id, c.employee_sub, c.started_at, c.ended_at,"
        " w.blob, w.creator_ref, w.creator_signature FROM conversation_keys k"
        " JOIN conversations c ON c.tenant_id = k.tenant_id"
        "  AND c.conversation_id = k.conversation_id"
        " JOIN key_wraps w ON w.tenant_id = k.tenant_id AND w.key_id = k.key_id"
        "  AND w.recipient_kind = 'recovery' AND w.recipient_ref = $2"
        " WHERE k.key_id = ANY($1::uuid[]) ORDER BY k.conversation_id, k.key_id",
        [key.key_id for key in remaining],
        recovery_key_id,
    )
    return tuple(
        ApproverScopeKey(
            conversation_id=str(r["conversation_id"]),
            key_id=str(r["key_id"]),
            employee_sub=r["employee_sub"],
            started_at=r["started_at"],
            ended_at=r["ended_at"],
            recovery_blob=r["blob"],
            creator_ref=r["creator_ref"],
            creator_signature=bytes(r["creator_signature"]),
        )
        for r in rows
    )


async def insert_decision(
    connection: asyncpg.Connection,
    tenant_id: str,
    request_id: str,
    holder: tuple[int, int],
    sub: str,
    now: datetime,
    *,
    approval: Approval | None = None,
    reason: str | None = None,
) -> None:
    holder_index, attempt = holder
    signed = (
        None
        if approval is None
        else json.dumps(
            [
                [key_id, b64url(partial_hash(blob))]
                for key_id, blob in sorted(approval.partials.items())
            ]
        )
    )
    await connection.execute(
        "INSERT INTO recovery_decisions (tenant_id, request_id, holder_index, attempt,"
        " custodian_sub, decision, reason, signed_partials, approval_signature, decided_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        tenant_id,
        request_id,
        holder_index,
        attempt,
        sub,
        "declined" if approval is None else "approved",
        reason,
        signed,
        None if approval is None else approval.signature,
        now,
    )


async def decisions_of(connection: asyncpg.Connection, request_id: str) -> tuple[DecisionRow, ...]:
    rows = await connection.fetch(
        "SELECT d.*, EXISTS (SELECT 1 FROM recovery_rejections j"
        "  WHERE j.tenant_id = d.tenant_id AND j.request_id = d.request_id"
        "  AND j.holder_index = d.holder_index AND j.attempt = d.attempt) AS rejected"
        " FROM recovery_decisions d WHERE d.request_id = $1"
        " ORDER BY d.decided_at, d.holder_index, d.attempt",
        request_id,
    )
    return tuple(decision_row(row) for row in rows)


async def served_partials(
    connection: asyncpg.Connection,
    request: RequestRow,
    remaining: tuple[ScopeKey, ...],
    approvals: Sequence[Any],
) -> ServedPartials:
    key_ids = [key.key_id for key in remaining]
    wraps = await connection.fetch(
        "SELECT k.conversation_id, w.key_id, w.blob, w.creator_ref, w.creator_signature"
        " FROM key_wraps w JOIN conversation_keys k ON k.tenant_id = w.tenant_id"
        "  AND k.key_id = w.key_id WHERE w.key_id = ANY($1::uuid[])"
        " AND w.recipient_kind = 'recovery' AND w.recipient_ref = $2 ORDER BY w.key_id",
        key_ids,
        request.recovery_key_id,
    )
    blobs = await connection.fetch(
        "SELECT holder_index, attempt, key_id, blob FROM recovery_partials"
        " WHERE request_id = $1 AND key_id = ANY($2::uuid[])",
        request.request_id,
        key_ids,
    )
    by_decision: dict[tuple[int, int], dict[str, str]] = {}
    for row in blobs:
        decision = by_decision.setdefault((row["holder_index"], row["attempt"]), {})
        decision[str(row["key_id"])] = row["blob"]
    return ServedPartials(
        wraps=tuple(
            ServedWrap(
                str(w["conversation_id"]),
                str(w["key_id"]),
                w["blob"],
                w["creator_ref"],
                bytes(w["creator_signature"]),
            )
            for w in wraps
        ),
        approvals=tuple(
            ServedApproval(
                holder_index=a["holder_index"],
                attempt=a["attempt"],
                signed_partials=signed_partials(a["signed_partials"]),
                approval_signature=bytes(a["approval_signature"]),
                blobs=by_decision.get((a["holder_index"], a["attempt"]), {}),
            )
            for a in approvals
        ),
        holders_ceremony_id=request.holders_ceremony_id,
    )


async def has_k_approvals(connection: asyncpg.Connection, request: RequestRow) -> bool:
    """k approvals that count: approved, not since rejected, one per custodian."""
    k = await recovery_k(connection, request)
    approvals = await connection.fetch(VALID_APPROVALS, request.request_id)
    return len({row["holder_index"] for row in approvals}) >= k


async def recovery_k(connection: asyncpg.Connection, request: RequestRow) -> int:
    """The k of the holders the request was filed under: a resharing never moves it (§9.7)."""
    k: int = await connection.fetchval(
        "SELECT k FROM recovery_ceremonies WHERE ceremony_id = $1", request.holders_ceremony_id
    )
    return k


def wraps_refusal(
    posted: dict[str, NewWrap], remaining: tuple[ScopeKey, ...], verify: WrapVerifier
) -> Refused | None:
    if not {key.key_id for key in remaining} <= posted.keys():
        return Refused("scope_not_covered")
    for key in remaining:
        wrap = posted[key.key_id]
        if wrap.conversation_id != key.conversation_id or not verify(wrap):
            return Refused("signature_invalid")
    return None


async def close_lapsed(connection: asyncpg.Connection, request: NewRequest) -> None:
    """A lapsed request of the requester closes before another is filed (§9.5).

    Expiry is lazy; left open, its partials would sit beside the new request's,
    and two partials for one R from two requests open the key together.
    """
    rows = await connection.fetch(
        "SELECT request_id FROM recovery_requests WHERE requester_sub = $1"
        " AND status = 'open' AND expires_at <= $2 ORDER BY request_id FOR UPDATE",
        request.requester_sub,
        request.created_at,
    )
    for row in rows:
        await close_request(
            connection,
            request.tenant_id,
            str(row["request_id"]),
            "expired",
            SYSTEM_ACTOR,
            request.created_at,
        )


def _fileable(request: NewRequest, row: Any) -> bool:
    """Recoverable, and for a key recovery the requester's own conversation (§9.6)."""
    if row is None or not row["recoverable"]:
        return False
    return request.kind != "key_recovery" or row["employee_sub"] == request.requester_sub


async def filing_refusal(connection: asyncpg.Connection, request: NewRequest) -> Refused | None:
    # One key recovery at a time: the next batch is filed once this one closes (§9.6).
    if request.kind == "key_recovery" and await connection.fetchval(
        OPEN_KEY_RECOVERY, request.requester_sub, request.created_at
    ):
        return Refused("request_exists")
    checked = {
        str(row["conversation_id"]): row
        for row in await connection.fetch(
            FILING_CHECK,
            list(request.conversation_ids),
            request.created_at,
            request.recovery_key_id,
            request.requester_sub,
        )
    }
    missing = [cid for cid in request.conversation_ids if not _fileable(request, checked.get(cid))]
    if missing:
        await append_audits(
            connection,
            [
                AuditEvent(
                    request.tenant_id,
                    request.requester_sub,
                    "recording.archive.not_found",
                    cid,
                    request.created_at,
                )
                for cid in missing
            ],
        )
        return Refused("not_found")
    if any(checked[cid]["accessible"] for cid in request.conversation_ids):
        return Refused("already_accessible")
    if any(checked[cid]["requested"] for cid in request.conversation_ids):
        return Refused("request_exists")
    return None


async def insert_request(
    connection: asyncpg.Connection,
    request: NewRequest,
    scope: tuple[ScopeKey, ...],
    holders_ceremony_id: str,
) -> None:
    now = request.created_at
    await connection.execute(
        "INSERT INTO recovery_requests (tenant_id, request_id, kind, requester_sub,"
        " requester_key_version, recovery_key_id, reason, request_signature, status,"
        " created_at, expires_at, holders_ceremony_id) VALUES ($1, $2, $10, $3, $4, $5, $6,"
        " $7, 'open', $8, $9, $11)",
        request.tenant_id,
        request.request_id,
        request.requester_sub,
        request.requester_key_version,
        request.recovery_key_id,
        request.reason,
        request.signature,
        now,
        now + REQUEST_LIFETIME,
        request.kind,
        holders_ceremony_id,
    )
    await connection.executemany(
        "INSERT INTO recovery_request_keys VALUES ($1, $2, $3, $4)",
        [(request.tenant_id, request.request_id, k.conversation_id, k.key_id) for k in scope],
    )
    await append_audit(
        connection,
        AuditEvent(
            request.tenant_id,
            request.requester_sub,
            "recovery.request.filed",
            request.request_id,
            now,
        ),
    )


async def record_unrecoverable(
    connection: asyncpg.Connection,
    tenant_id: str,
    sub: str,
    request_id: str,
    remaining: tuple[ScopeKey, ...],
    lost: Sequence[UnrecoverableKey],
    now: datetime,
) -> list[AuditEvent]:
    """One statement for every key the requester could not use; their audit, unappended.

    Only the requester reports, and it only narrows their own access: no proof is asked.
    """
    if not lost:
        return []
    conversations = {key.key_id: key.conversation_id for key in remaining}
    ordered = sorted(lost, key=lambda item: item.key_id)
    await connection.execute(
        "INSERT INTO recovery_unrecoverable_keys"
        " SELECT $1, $2, u.conversation_id, u.key_id, u.stage, $3"
        " FROM unnest($4::uuid[], $5::uuid[], $6::text[]) AS u(conversation_id, key_id, stage)"
        " ON CONFLICT DO NOTHING",
        tenant_id,
        request_id,
        now,
        [conversations[item.key_id] for item in ordered],
        [item.key_id for item in ordered],
        [item.stage for item in ordered],
    )
    return [
        AuditEvent(tenant_id, sub, f"recovery.integrity_failure.{item.stage}", item.key_id, now)
        for item in ordered
    ]
