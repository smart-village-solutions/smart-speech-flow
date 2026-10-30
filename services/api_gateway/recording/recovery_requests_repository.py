"""Postgres access for recovery requests (spec §9.5, §9.6; migrations 006, 007).

Each write commits together with its audit event; the locked reads and the
shared writes live in `recovery_requests_writes`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .recovery_requests_model import (
    LIMITS,
    UNRECOVERABLE_STAGES,
    Approval,
    ApprovalContext,
    ApprovalVerifier,
    Candidate,
    NewRequest,
    NewWrap,
    Progress,
    Refused,
    RequestRow,
    ScopeKey,
    ScopeVerifier,
    ServedPartials,
    UnrecoverableKey,
    WrapVerifier,
)
from .recovery_requests_sql import (
    APPROVABLE,
    CANDIDATES,
    OWN_CANDIDATES,
    OWN_REQUESTS,
    OWN_TOTALS,
    STALE_HOLDER,
    VALID_APPROVALS,
    candidate_of,
    listed,
    scope_of,
)
from .recovery_requests_writes import (
    approver_keys,
    close_lapsed,
    close_request,
    decidable_by,
    decisions_of,
    filing_refusal,
    has_k_approvals,
    insert_decision,
    insert_request,
    not_found,
    own_request,
    record_unrecoverable,
    recovery_k,
    requester_key,
    served_partials,
    wraps_refusal,
)
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)

# Re-exported: the retention worker closes lapsed requests the same way (§9.5).
__all__ = ["PostgresRecoveryRequests", "close_request"]

T = TypeVar("T")


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

        return [candidate_of(row) for row in await self._run(tenant_id, work)]

    async def own_candidates(
        self, tenant_id: str, sub: str, recovery_key_id: str, now: datetime
    ) -> tuple[list[Candidate], int, int]:
        """The next batch of whole conversations, newest first, and what lies beyond it (§9.6)."""

        async def work(connection: asyncpg.Connection) -> tuple[Any, Any]:
            rows = await connection.fetch(OWN_CANDIDATES, None, now, recovery_key_id, sub)
            totals = await connection.fetchrow(OWN_TOTALS, None, now, recovery_key_id, sub)
            return rows, totals

        rows, totals = await self._run(tenant_id, work)
        batch = batched([candidate_of(row) for row in rows])
        keys = sum(len(candidate.key_ids) for candidate in batch)
        return (
            batch,
            max(int(totals["conversations"]) - len(batch), 0),
            max(int(totals["keys"]) - keys, 0),
        )

    async def file(
        self, request: NewRequest, verify: ScopeVerifier
    ) -> Refused | tuple[ScopeKey, ...]:
        tenant_id = request.tenant_id
        max_conversations, max_keys = LIMITS[request.kind]

        async def work(connection: asyncpg.Connection) -> Refused | tuple[ScopeKey, ...]:
            key_version = await requester_key(connection, request.requester_sub)
            if key_version != request.requester_key_version:
                return Refused("key_changed")
            # Two filings by one requester serialise, so "one open request per conversation" holds.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"ssf-recovery-filing:{tenant_id}:{request.requester_sub}",
            )
            await close_lapsed(connection, request)
            if len(request.conversation_ids) > max_conversations:
                return Refused("scope_too_large")
            refused = await filing_refusal(connection, request)
            if refused is not None:
                return refused
            scope = scope_of(
                await connection.fetch(
                    "SELECT conversation_id, key_id FROM conversation_keys"
                    " WHERE conversation_id = ANY($1::uuid[]) ORDER BY conversation_id, key_id",
                    list(request.conversation_ids),
                )
            )
            if len(scope) > max_keys:
                return Refused("scope_too_large")
            if not verify(scope):
                return Refused("signature_invalid")
            try:
                async with connection.transaction():
                    await insert_request(connection, request, scope)
            except asyncpg.UniqueViolationError:
                return Refused("request_exists")  # a reused request ID
            return scope

        return await self._run(tenant_id, work)

    async def own_requests(
        self, tenant_id: str, sub: str, now: datetime, kind: str | None = None
    ) -> list[tuple[RequestRow, int]]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(OWN_REQUESTS, sub, kind)

        return [listed(row, now) for row in await self._run(tenant_id, work)]

    async def approvals(
        self, tenant_id: str, sub: str, recovery_key_id: str, now: datetime
    ) -> list[tuple[RequestRow, int]]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(APPROVABLE, recovery_key_id, sub, now)

        return [listed(row, now) for row in await self._run(tenant_id, work)]

    async def share_stale(self, tenant_id: str, sub: str, recovery_key_id: str) -> bool:
        """Whether the caller holds a share their active key cannot open (§9.6)."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval(STALE_HOLDER, recovery_key_id, sub)

        return bool(await self._run(tenant_id, work))

    async def approval_context(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | ApprovalContext:
        async def work(connection: asyncpg.Connection) -> Refused | ApprovalContext:
            checked = await decidable_by(connection, tenant_id, sub, request_id, now)
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
                remaining=await approver_keys(connection, remaining, request.recovery_key_id),
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
            checked = await decidable_by(connection, tenant_id, sub, request_id, now)
            if isinstance(checked, Refused):
                return checked
            holder, attempt, _, remaining = checked
            index = holder["holder_index"]
            if not verify(index, attempt, bytes(holder["sig_pub"])):
                return Refused("signature_invalid")
            # Keys that left the scope since the custodian loaded it are dropped, not refused.
            if not {key.key_id for key in remaining} <= approval.partials.keys():
                return Refused("scope_not_covered")
            await insert_decision(
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
            checked = await decidable_by(connection, tenant_id, sub, request_id, now)
            if isinstance(checked, Refused):
                return checked
            holder, attempt, _, _ = checked
            await insert_decision(
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
        self, tenant_id: str, sub: str, request_id: str, now: datetime, *, may_supervise: bool
    ) -> Refused | Progress:
        async def work(connection: asyncpg.Connection) -> Refused | Progress:
            owned = await own_request(connection, tenant_id, sub, request_id, now, may_supervise)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            return Progress(
                request=request,
                k=await recovery_k(connection, request.recovery_key_id),
                decisions=await decisions_of(connection, request_id),
                remaining=remaining,
                conversations=await connection.fetchval(
                    "SELECT count(DISTINCT conversation_id) FROM recovery_request_keys"
                    " WHERE request_id = $1",
                    request_id,
                ),
            )

        return await self._run(tenant_id, work)

    async def partials(
        self, tenant_id: str, sub: str, request_id: str, now: datetime, *, may_supervise: bool
    ) -> Refused | ServedPartials:
        async def work(connection: asyncpg.Connection) -> Refused | ServedPartials:
            key_version = await requester_key(connection, sub)
            owned = await own_request(connection, tenant_id, sub, request_id, now, may_supervise)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            if request.status != "open":
                return Refused("closed")
            if key_version != request.requester_key_version:
                return Refused("key_changed")
            if not await has_k_approvals(connection, request):
                return Refused("not_enough_approvals")
            approvals = await connection.fetch(VALID_APPROVALS, request_id)
            served = await served_partials(connection, request, remaining, approvals)
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
        *,
        may_supervise: bool,
    ) -> Refused | None:
        holder_index, attempt = holder

        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await own_request(connection, tenant_id, sub, request_id, now, may_supervise)
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
                return await not_found(connection, tenant_id, sub, request_id, now)
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
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        stage: str,
        now: datetime,
        *,
        may_supervise: bool,
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await own_request(connection, tenant_id, sub, request_id, now, may_supervise)
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
        *,
        may_supervise: bool,
        unrecoverable: Sequence[UnrecoverableKey] = (),
    ) -> Refused | tuple[str, ...]:
        """Every remaining key in one transaction; returns the posted keys that left the scope.

        A key whose recovery wrap the browser could not use comes in `unrecoverable`
        instead of as a wrap, so one bad wrap blocks no batch and is recorded with the rest.
        """

        async def work(connection: asyncpg.Connection) -> Refused | tuple[str, ...]:
            locked_version = await requester_key(connection, sub)
            owned = await own_request(connection, tenant_id, sub, request_id, now, may_supervise)
            if isinstance(owned, Refused):
                return owned
            request, remaining = owned
            scope_ids = {key.key_id for key in remaining}
            if request.status != "open":
                return Refused("closed")
            # The partials were sealed to the key the request names; a newer key cannot sign for it.
            if locked_version != request.requester_key_version or key_version != locked_version:
                return Refused("key_changed")
            # Wraps the requester made without k approvals open nothing, but would
            # complete the request and list the conversation: refuse them (§9.5).
            if not await has_k_approvals(connection, request):
                return Refused("not_enough_approvals")
            posted = {wrap.key_id: wrap for wrap in wraps}
            if any(item.stage not in UNRECOVERABLE_STAGES for item in unrecoverable):
                return Refused("bad_stage")
            # Keys that left the scope since the partials were served need no record.
            lost = {item.key_id: item for item in unrecoverable if item.key_id in scope_ids}
            required = tuple(key for key in remaining if key.key_id not in lost)
            refused = wraps_refusal(posted, required, verify)
            if refused is not None:
                return refused
            lost_events = await record_unrecoverable(
                connection, tenant_id, sub, request_id, remaining, list(lost.values()), now
            )
            wanted = [key.key_id for key in required]
            # One statement for the whole scope: a wrap the caller already holds stays,
            # and only the new ones come back to be audited.
            stored = await connection.fetch(
                "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
                " creator_ref, creator_signature, granted_at)"
                " SELECT $1, w.key_id, 'user', $2, w.blob, $2, w.signature, $3"
                " FROM unnest($4::uuid[], $5::text[], $6::bytea[]) AS w(key_id, blob, signature)"
                " ON CONFLICT (tenant_id, key_id, recipient_kind, recipient_ref) DO NOTHING"
                " RETURNING key_id",
                tenant_id,
                sub,
                now,
                wanted,
                [posted[key_id].blob for key_id in wanted],
                [posted[key_id].signature for key_id in wanted],
            )
            events = lost_events + [
                AuditEvent(tenant_id, sub, "recovery.wrap.stored", key_id, now)
                for key_id in sorted(str(row["key_id"]) for row in stored)
            ]
            await close_request(connection, tenant_id, request_id, "completed", sub, now, events)
            return tuple(sorted(posted.keys() - set(wanted)))

        return await self._run(tenant_id, work)

    async def cancel(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | None:
        """Allowed without `supervise`: a requester whose permission went may still withdraw."""

        async def work(connection: asyncpg.Connection) -> Refused | None:
            owned = await own_request(connection, tenant_id, sub, request_id, now, True)
            if isinstance(owned, Refused):
                return owned
            if owned[0].status != "open":
                return Refused("closed")
            await close_request(connection, tenant_id, request_id, "cancelled", sub, now)
            return None

        return await self._run(tenant_id, work)


def batched(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Whole conversations up to the key limit, stopping at the first that does not fit.

    A conversation over the limit can never be filed (one key per gateway restart
    makes it unreachable in practice), so it is passed over.
    """
    _, max_keys = LIMITS["key_recovery"]
    batch: list[Candidate] = []
    keys = 0
    for candidate in candidates:
        size = len(candidate.key_ids)
        if size > max_keys:
            continue
        if keys + size > max_keys:
            break
        batch.append(candidate)
        keys += size
    return batch
