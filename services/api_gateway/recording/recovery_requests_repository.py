"""Postgres access for exceptional access (spec §9.5; migration 006).

Every write locks the request row first and applies a due expiry or an empty
scope before anything else, so a step can never land on a request that has
already lapsed. Each write commits together with its audit event; a refusal
that must be recorded is returned as `Refused`, so its transaction commits too.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .crypto.encoding import b64url
from .crypto.signatures import partial_hash
from .recovery_requests_model import (
    MAX_SCOPE_KEYS,
    REQUEST_LIFETIME,
    SYSTEM_ACTOR,
    Approval,
    ApprovalContext,
    ApprovalVerifier,
    ApproverScopeKey,
    Candidate,
    DecisionRow,
    NewRequest,
    NewWrap,
    Progress,
    Refused,
    RequestRow,
    ScopeKey,
    ScopeVerifier,
    ServedApproval,
    ServedPartials,
    ServedWrap,
    WrapVerifier,
)
from .recovery_requests_sql import (
    APPROVABLE,
    CANDIDATES,
    FILING_CHECK,
    HOLDER,
    LATEST_DECISION,
    OWN_REQUESTS,
    REMAINING_LOCKED,
    VALID_APPROVALS,
    decision_row,
    listed,
    replaced,
    request_row,
    scope_of,
    signed_partials,
)
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)

T = TypeVar("T")


async def close_request(
    connection: asyncpg.Connection,
    tenant_id: str,
    request_id: str,
    status: str,
    actor: str,
    now: datetime,
) -> None:
    await connection.execute(
        "UPDATE recovery_requests SET status = $2, closed_at = $3"
        " WHERE request_id = $1 AND status = 'open'",
        request_id,
        status,
        now,
    )
    await connection.execute("DELETE FROM recovery_partials WHERE request_id = $1", request_id)
    event = f"recovery.request.{status}"
    await append_audit(connection, AuditEvent(tenant_id, actor, event, request_id, now))


async def _locked(
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


async def _owned(
    connection: asyncpg.Connection, tenant_id: str, sub: str, request_id: str, now: datetime
) -> Refused | tuple[RequestRow, tuple[ScopeKey, ...]]:
    """The caller's own request under lock; another's reads as unknown."""
    locked = await _locked(connection, tenant_id, request_id, now)
    if locked is None or locked[0].requester_sub != sub:
        return await _not_found(connection, tenant_id, sub, request_id, now)
    return locked


async def _not_found(
    connection: asyncpg.Connection, tenant_id: str, sub: str, request_id: str, now: datetime
) -> Refused:
    await append_audit(
        connection, AuditEvent(tenant_id, sub, "recovery.request.not_found", request_id, now)
    )
    return Refused("not_found")


async def _next_attempt(
    connection: asyncpg.Connection, request_id: str, holder_index: int
) -> int | None:
    """1 for a first decision; the next number after a rejected approval; else None."""
    latest = await connection.fetchrow(LATEST_DECISION, request_id, holder_index)
    if latest is None:
        return 1
    if latest["decision"] == "approved" and latest["rejected"]:
        return int(latest["attempt"]) + 1
    return None


async def _decidable(
    connection: asyncpg.Connection, tenant_id: str, sub: str, request_id: str, now: datetime
) -> Refused | tuple[Any, int, RequestRow, tuple[ScopeKey, ...]]:
    """The one path of the eligibility rules: detail, approval and decline all use it."""
    locked = await _locked(connection, tenant_id, request_id, now)
    if locked is None:
        return await _not_found(connection, tenant_id, sub, request_id, now)
    request, remaining = locked
    # The requester can see the request, so they learn why, share or not.
    if request.requester_sub == sub:
        await append_audit(
            connection, AuditEvent(tenant_id, sub, "recovery.approval.refused", request_id, now)
        )
        return Refused("requester_cannot_approve")
    holder = await connection.fetchrow(HOLDER, request.recovery_key_id, sub)
    if holder is None:
        return await _not_found(connection, tenant_id, sub, request_id, now)
    if request.status != "open":
        return Refused("closed")
    attempt = await _next_attempt(connection, request_id, holder["holder_index"])
    if attempt is None:
        return Refused("already_decided")
    return holder, attempt, request, remaining


async def _approver_keys(
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


async def _insert_decision(
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


async def _decisions(connection: asyncpg.Connection, request_id: str) -> tuple[DecisionRow, ...]:
    rows = await connection.fetch(
        "SELECT d.*, EXISTS (SELECT 1 FROM recovery_rejections j"
        "  WHERE j.tenant_id = d.tenant_id AND j.request_id = d.request_id"
        "  AND j.holder_index = d.holder_index AND j.attempt = d.attempt) AS rejected"
        " FROM recovery_decisions d WHERE d.request_id = $1"
        " ORDER BY d.decided_at, d.holder_index, d.attempt",
        request_id,
    )
    return tuple(decision_row(row) for row in rows)


async def _served(
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
    )


async def _approved(connection: asyncpg.Connection, request: RequestRow) -> bool:
    """k approvals that count: approved, not since rejected, one per custodian."""
    k = await _recovery_k(connection, request.recovery_key_id)
    approvals = await connection.fetch(VALID_APPROVALS, request.request_id)
    return len({row["holder_index"] for row in approvals}) >= k


async def _recovery_k(connection: asyncpg.Connection, recovery_key_id: str) -> int:
    k: int = await connection.fetchval(
        "SELECT k FROM recovery_keys WHERE key_id = $1", recovery_key_id
    )
    return k


class PostgresRecoveryRequests:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _run(self, tenant_id: str, work: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        try:
            async with (
                self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection,
                connection.transaction(),
            ):
                await bind_tenant(connection, tenant_id)
                return await work(connection)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def employees(self, tenant_id: str) -> list[str]:
        async def work(connection: asyncpg.Connection) -> list[str]:
            rows = await connection.fetch(
                "SELECT DISTINCT employee_sub FROM conversations WHERE ended_at IS NOT NULL"
                " ORDER BY employee_sub"
            )
            return [row["employee_sub"] for row in rows]

        return await self._run(tenant_id, work)

    async def candidates(
        self,
        tenant_id: str,
        requester: str,
        employee: str,
        recovery_key_id: str,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> list[Candidate]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                CANDIDATES, employee, now, recovery_key_id, requester, start, end
            )

        return [
            Candidate(
                conversation_id=str(row["conversation_id"]),
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                retention_until=row["retention_until"],
                legal_hold=row["legal_hold"],
                incomplete=row["incomplete"],
                key_ids=tuple(row["key_ids"]),
            )
            for row in await self._run(tenant_id, work)
        ]

    async def file(
        self, request: NewRequest, verify: ScopeVerifier
    ) -> Refused | tuple[ScopeKey, ...]:
        tenant_id = request.tenant_id

        async def work(connection: asyncpg.Connection) -> Refused | tuple[ScopeKey, ...]:
            # Two filings by one requester serialise, so "one open request per conversation" holds.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"ssf-recovery-filing:{tenant_id}:{request.requester_sub}",
            )
            await _close_lapsed(connection, request)
            refused = await _filing_refusal(connection, request)
            if refused is not None:
                return refused
            scope = scope_of(
                await connection.fetch(
                    "SELECT conversation_id, key_id FROM conversation_keys"
                    " WHERE conversation_id = ANY($1::uuid[]) ORDER BY conversation_id, key_id",
                    list(request.conversation_ids),
                )
            )
            if len(scope) > MAX_SCOPE_KEYS:
                return Refused("scope_too_large")
            if not verify(scope):
                return Refused("signature_invalid")
            try:
                async with connection.transaction():
                    await _insert_request(connection, request, scope)
            except asyncpg.UniqueViolationError:
                return Refused("request_exists")  # a reused request ID
            return scope

        return await self._run(tenant_id, work)

    async def own_requests(
        self, tenant_id: str, sub: str, now: datetime
    ) -> list[tuple[RequestRow, int]]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(OWN_REQUESTS, sub)

        return [listed(row, now) for row in await self._run(tenant_id, work)]

    async def approvals(
        self, tenant_id: str, sub: str, recovery_key_id: str, now: datetime
    ) -> list[tuple[RequestRow, int]]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(APPROVABLE, recovery_key_id, sub, now)

        return [listed(row, now) for row in await self._run(tenant_id, work)]

    async def approval_context(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | ApprovalContext:
        async def work(connection: asyncpg.Connection) -> Refused | ApprovalContext:
            checked = await _decidable(connection, tenant_id, sub, request_id, now)
            if isinstance(checked, Refused):
                return checked
            holder, attempt, request, remaining = checked
            keys = await connection.fetchrow(
                "SELECT enc_pub, sig_pub FROM user_keys WHERE user_sub = $1 AND key_version = $2",
                request.requester_sub,
                request.requester_key_version,
            )
            signed = scope_of(
                await connection.fetch(
                    "SELECT conversation_id, key_id FROM recovery_request_keys"
                    " WHERE request_id = $1 ORDER BY conversation_id, key_id",
                    request_id,
                )
            )
            return ApprovalContext(
                request=request,
                requester_enc_pub=bytes(keys["enc_pub"]),
                requester_sig_pub=bytes(keys["sig_pub"]),
                signed_scope=signed,
                remaining=await _approver_keys(connection, remaining, request.recovery_key_id),
                holder_index=holder["holder_index"],
                attempt=attempt,
                encrypted_share=holder["encrypted_share"],
            )

        return await self._run(tenant_id, work)

    async def approve(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        approval: Approval,
        verify: ApprovalVerifier,
        now: datetime,
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            checked = await _decidable(connection, tenant_id, sub, request_id, now)
            if isinstance(checked, Refused):
                return checked
            holder, attempt, _, remaining = checked
            index = holder["holder_index"]
            if not verify(index, attempt, bytes(holder["sig_pub"])):
                return Refused("signature_invalid")
            # Keys that left the scope since the custodian loaded it are dropped, not refused.
            if not {key.key_id for key in remaining} <= approval.partials.keys():
                return Refused("scope_not_covered")
            await _insert_decision(
                connection, tenant_id, request_id, (index, attempt), sub, now, approval=approval
            )
            await connection.executemany(
                "INSERT INTO recovery_partials VALUES ($1, $2, $3, $4, $5, $6, $7)",
                [
                    (
                        tenant_id,
                        request_id,
                        index,
                        attempt,
                        key.conversation_id,
                        key.key_id,
                        approval.partials[key.key_id],
                    )
                    for key in remaining
                ],
            )
            await append_audit(
                connection, AuditEvent(tenant_id, sub, "recovery.request.approved", request_id, now)
            )
            return None

        return await self._run(tenant_id, work)

    async def decline(
        self, tenant_id: str, sub: str, request_id: str, reason: str, now: datetime
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            checked = await _decidable(connection, tenant_id, sub, request_id, now)
            if isinstance(checked, Refused):
                return checked
            holder, attempt, _, _ = checked
            await _insert_decision(
                connection,
                tenant_id,
                request_id,
                (holder["holder_index"], attempt),
                sub,
                now,
                reason=reason,
            )
            await append_audit(
                connection, AuditEvent(tenant_id, sub, "recovery.request.declined", request_id, now)
            )
            return None

        return await self._run(tenant_id, work)

    async def progress(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | Progress:
        async def work(connection: asyncpg.Connection) -> Refused | Progress:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            return Progress(
                request=request,
                k=await _recovery_k(connection, request.recovery_key_id),
                decisions=await _decisions(connection, request_id),
                remaining=remaining,
                conversations=await connection.fetchval(
                    "SELECT count(DISTINCT conversation_id) FROM recovery_request_keys"
                    " WHERE request_id = $1",
                    request_id,
                ),
            )

        return await self._run(tenant_id, work)

    async def partials(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | ServedPartials:
        async def work(connection: asyncpg.Connection) -> Refused | ServedPartials:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            if request.status != "open":
                return Refused("closed")
            if not await _approved(connection, request):
                return Refused("not_enough_approvals")
            approvals = await connection.fetch(VALID_APPROVALS, request_id)
            served = await _served(connection, request, remaining, approvals)
            await append_audit(
                connection, AuditEvent(tenant_id, sub, "recovery.partials.served", request_id, now)
            )
            return served

        return await self._run(tenant_id, work)

    async def reject(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        holder: tuple[int, int],
        fault: str,
        now: datetime,
    ) -> Refused | None:
        holder_index, attempt = holder

        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            if owned[0].status != "open":
                return Refused("closed")
            approved = await connection.fetchval(
                "SELECT decision = 'approved' FROM recovery_decisions"
                " WHERE request_id = $1 AND holder_index = $2 AND attempt = $3",
                request_id,
                holder_index,
                attempt,
            )
            if not approved:
                return await _not_found(connection, tenant_id, sub, request_id, now)
            await connection.execute(
                "INSERT INTO recovery_rejections VALUES ($1, $2, $3, $4, $5, $6)"
                " ON CONFLICT DO NOTHING",
                tenant_id,
                request_id,
                holder_index,
                attempt,
                fault,
                now,
            )
            await connection.execute(
                "DELETE FROM recovery_partials WHERE request_id = $1 AND holder_index = $2"
                " AND attempt = $3",
                request_id,
                holder_index,
                attempt,
            )
            ref = f"{request_id}:{holder_index}:{attempt}"
            await append_audit(
                connection, AuditEvent(tenant_id, sub, "recovery.partial.rejected", ref, now)
            )
            return None

        return await self._run(tenant_id, work)

    async def record_integrity_failure(
        self, tenant_id: str, sub: str, request_id: str, stage: str, now: datetime
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            if owned[0].status != "open":
                return Refused("closed")
            event = f"recovery.integrity_failure.{stage}"
            await append_audit(connection, AuditEvent(tenant_id, sub, event, request_id, now))
            return None

        return await self._run(tenant_id, work)

    async def store_wraps(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        wraps: Sequence[NewWrap],
        key_version: int,
        verify: WrapVerifier,
        now: datetime,
    ) -> Refused | tuple[str, ...]:
        """Every remaining key in one transaction; returns the posted keys that left the scope."""

        async def work(connection: asyncpg.Connection) -> Refused | tuple[str, ...]:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            if request.status != "open":
                return Refused("closed")
            # The partials were sealed to the key the request names; a newer key cannot sign for it.
            if request.requester_key_version != key_version:
                return Refused("signature_invalid")
            # Wraps the requester made without k approvals open nothing, but would
            # complete the request and list the conversation: refuse them (§9.5).
            if not await _approved(connection, request):
                return Refused("not_enough_approvals")
            posted = {wrap.key_id: wrap for wrap in wraps}
            refused = _wraps_refusal(posted, remaining, verify)
            if refused is not None:
                return refused
            wanted = [key.key_id for key in remaining]
            for key_id in wanted:
                # A wrap the caller already holds for this key stays; only a new one is audited.
                stored = await connection.fetchval(
                    "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
                    " creator_ref, creator_signature, granted_at)"
                    " VALUES ($1, $2, 'user', $3, $4, $3, $5, $6)"
                    " ON CONFLICT (tenant_id, key_id, recipient_kind, recipient_ref) DO NOTHING"
                    " RETURNING key_id",
                    tenant_id,
                    key_id,
                    sub,
                    posted[key_id].blob,
                    posted[key_id].signature,
                    now,
                )
                if stored is not None:
                    await append_audit(
                        connection, AuditEvent(tenant_id, sub, "recovery.wrap.stored", key_id, now)
                    )
            await close_request(connection, tenant_id, request_id, "completed", sub, now)
            return tuple(sorted(posted.keys() - set(wanted)))

        return await self._run(tenant_id, work)

    async def cancel(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await _owned(connection, tenant_id, sub, request_id, now)
            if isinstance(owned, Refused):
                return owned
            if owned[0].status != "open":
                return Refused("closed")
            await close_request(connection, tenant_id, request_id, "cancelled", sub, now)
            return None

        return await self._run(tenant_id, work)


def _wraps_refusal(
    posted: dict[str, NewWrap], remaining: tuple[ScopeKey, ...], verify: WrapVerifier
) -> Refused | None:
    if not {key.key_id for key in remaining} <= posted.keys():
        return Refused("scope_not_covered")
    for key in remaining:
        wrap = posted[key.key_id]
        if wrap.conversation_id != key.conversation_id or not verify(wrap):
            return Refused("signature_invalid")
    return None


async def _close_lapsed(connection: asyncpg.Connection, request: NewRequest) -> None:
    """A lapsed request of the requester closes before another is filed (§9.5).

    Expiry is lazy; left open, its partials would sit beside the new request's,
    and two partials for one R from two requests open the key together.
    """
    rows = await connection.fetch(
        "SELECT request_id FROM recovery_requests WHERE requester_sub = $1"
        " AND status = 'open' AND expires_at <= $2 FOR UPDATE",
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


async def _filing_refusal(connection: asyncpg.Connection, request: NewRequest) -> Refused | None:
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
    missing = [
        cid
        for cid in request.conversation_ids
        if cid not in checked or not checked[cid]["recoverable"]
    ]
    for cid in missing:
        await append_audit(
            connection,
            AuditEvent(
                request.tenant_id,
                request.requester_sub,
                "recording.archive.not_found",
                cid,
                request.created_at,
            ),
        )
    if missing:
        return Refused("not_found")
    if any(checked[cid]["accessible"] for cid in request.conversation_ids):
        return Refused("already_accessible")
    if any(checked[cid]["requested"] for cid in request.conversation_ids):
        return Refused("request_exists")
    return None


async def _insert_request(
    connection: asyncpg.Connection, request: NewRequest, scope: tuple[ScopeKey, ...]
) -> None:
    now = request.created_at
    await connection.execute(
        "INSERT INTO recovery_requests (tenant_id, request_id, kind, requester_sub,"
        " requester_key_version, recovery_key_id, reason, request_signature, status,"
        " created_at, expires_at) VALUES ($1, $2, 'access', $3, $4, $5, $6, $7, 'open',"
        " $8, $9)",
        request.tenant_id,
        request.request_id,
        request.requester_sub,
        request.requester_key_version,
        request.recovery_key_id,
        request.reason,
        request.signature,
        now,
        now + REQUEST_LIFETIME,
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
