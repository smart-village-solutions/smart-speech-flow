"""Postgres access for resharing (spec §9.7; migration 008).

The activation runs inside the confirmation that completes a resharing,
under the ceremony row's lock, in the order every recovery writer keeps:
the key row, then the open requests by ID, then their conversations, then
the writes, and the audit last in one batch. A filing holds the key row
shared, so it is either seen and closed here or filed under the new holders.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .ceremony_model import (
    CeremonyDealer,
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    conflict,
)
from .ceremony_rows import (
    OPEN,
    clear_subshares,
    close_lapsed,
    gateway_keys_json,
    insert_holders,
    participant_row,
    snapshot_of,
)
from .recovery_requests_model import SYSTEM_ACTOR
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audits,
    bind_tenant,
    storage_unavailable,
    user_key_from_row,
)
from .resharing import DealerMaterial
from .resharing_model import HolderGeneration, end_to_end_holds, new_public_shares

T = TypeVar("T")

# The current generation's custodian holding `index`, by `ref`, and the key that opens its
# share: the active one, or a retired one whose blob re-enrolment kept (§9.6).
_DEALER_KEY = (
    "SELECT s.encrypted_share, u.* FROM recovery_keys r"
    " JOIN recovery_shares s ON s.tenant_id = r.tenant_id"
    "  AND s.ceremony_id = r.holders_ceremony_id AND s.encrypted_share IS NOT NULL"
    " JOIN ceremony_participants p ON p.tenant_id = s.tenant_id"
    "  AND p.ceremony_id = s.ceremony_id AND p.holder_index = s.holder_index"
    "  AND p.kind = 'custodian'"
    " JOIN user_keys u ON u.tenant_id = p.tenant_id AND u.user_sub = p.holder_ref"
    "  AND u.fingerprint = p.fingerprint"
    "  AND (u.retired_at IS NULL OR u.encrypted_private IS NOT NULL)"
    " WHERE r.status = 'active'"
)


_HOLDER_KEY = (
    "SELECT 1 FROM user_keys u WHERE u.tenant_id = p.tenant_id AND u.user_sub = p.holder_ref"
    " AND u.fingerprint = p.fingerprint"
)
_HOLDER_STATES = (
    "SELECT p.holder_ref, CASE"
    f" WHEN EXISTS ({_HOLDER_KEY} AND u.retired_at IS NULL) THEN 'fresh'"
    f" WHEN EXISTS ({_HOLDER_KEY} AND u.encrypted_private IS NOT NULL) THEN 'kept'"
    " ELSE 'lost' END AS state"
    " FROM recovery_keys r JOIN ceremony_participants p ON p.tenant_id = r.tenant_id"
    "  AND p.ceremony_id = r.holders_ceremony_id AND p.kind = 'custodian'"
    " WHERE r.status = 'active'"
)


async def _run(
    pool: asyncpg.Pool, tenant_id: str, work: Callable[[asyncpg.Connection], Awaitable[T]]
) -> T:
    try:
        async with (
            pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection,
            connection.transaction(),
        ):
            await bind_tenant(connection, tenant_id)
            return await work(connection)
    except asyncpg.UniqueViolationError:
        raise  # the caller's to answer: it means another ceremony is open
    except DRIVER_FAILURE as error:
        raise storage_unavailable(error) from None


class ResharingRepositoryMixin:
    """The resharing's reads and its start, on the ceremony repository's pool."""

    _pool: asyncpg.Pool

    async def holder_generation(self, tenant_id: str) -> HolderGeneration | None:
        async def work(connection: asyncpg.Connection) -> HolderGeneration | None:
            key = await connection.fetchrow(
                "SELECT r.holders_ceremony_id, r.holders_transcript_hash, c.k"
                " FROM recovery_keys r JOIN recovery_ceremonies c"
                " ON c.tenant_id = r.tenant_id AND c.ceremony_id = r.holders_ceremony_id"
                " WHERE r.status = 'active'"
            )
            if key is None:
                return None
            holders = key["holders_ceremony_id"]
            participants = await connection.fetch(
                "SELECT * FROM ceremony_participants WHERE ceremony_id = $1"
                " ORDER BY holder_index",
                holders,
            )
            shares = await connection.fetch(
                "SELECT holder_index, holder_public_share FROM recovery_shares"
                " WHERE ceremony_id = $1",
                holders,
            )
            return HolderGeneration(
                ceremony_id=str(holders),
                k=key["k"],
                transcript_hash=bytes(key["holders_transcript_hash"]),
                participants=tuple(participant_row(row) for row in participants),
                public_shares={
                    row["holder_index"]: bytes(row["holder_public_share"]) for row in shares
                },
            )

        return await _run(self._pool, tenant_id, work)

    async def holder_states(self, tenant_id: str) -> dict[str, str]:
        """Each current custodian holder: 'fresh', 'kept' (re-enrolled, blob kept) or 'lost'."""

        async def work(connection: asyncpg.Connection) -> list[Any]:
            return list(await connection.fetch(_HOLDER_STATES))

        rows = await _run(self._pool, tenant_id, work)
        return {row["holder_ref"]: row["state"] for row in rows}

    async def dealer_material(
        self, tenant_id: str, dealer_index: int, holder_ref: str
    ) -> DealerMaterial | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(
                _DEALER_KEY + " AND s.holder_index = $1 AND p.holder_ref = $2"
                " ORDER BY u.key_version DESC LIMIT 1",
                dealer_index,
                holder_ref,
            )

        row = await _run(self._pool, tenant_id, work)
        if row is None:
            return None
        return DealerMaterial(dealer_index, row["encrypted_share"], user_key_from_row(row))

    async def create_resharing(
        self,
        ceremony: CeremonyRecord,
        participants: Sequence[CeremonyParticipant],
        dealers: Sequence[CeremonyDealer],
        audit: Sequence[AuditEvent],
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            # Shared, as a filing holds it: an activation in between moves the holders on.
            holders = await connection.fetchval(
                "SELECT holders_transcript_hash FROM recovery_keys"
                " WHERE key_id = $1 AND status = 'active' FOR SHARE",
                ceremony.recovery_key_id,
            )
            if holders is None or bytes(holders) != ceremony.previous_transcript_hash:
                raise conflict("HOLDERS_CHANGED", "The custodians changed; start again")
            await close_lapsed(connection, ceremony.started_at)
            await connection.execute(
                "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by,"
                " started_at, expires_at, status, gateway_keys, kind, recovery_key_id,"
                " previous_transcript_hash)"
                " VALUES ($1, $2, $3, $4, $5, $6, 'dealing', $7, 'resharing', $8, $9)",
                ceremony.tenant_id,
                ceremony.ceremony_id,
                ceremony.k,
                ceremony.started_by,
                ceremony.started_at,
                ceremony.expires_at,
                gateway_keys_json(ceremony.gateway_keys),
                ceremony.recovery_key_id,
                ceremony.previous_transcript_hash,
            )
            await insert_holders(connection, ceremony, participants, dealers)
            await append_audits(connection, audit)

        try:
            await _run(self._pool, ceremony.tenant_id, work)
        except asyncpg.UniqueViolationError:
            raise conflict("CEREMONY_IN_PROGRESS", "A ceremony is already in progress") from None

    async def chain(self, tenant_id: str, key_id: str) -> list[CeremonySnapshot]:
        """The key's first ceremony, then each completed resharing of it, in order."""

        async def work(connection: asyncpg.Connection) -> list[CeremonySnapshot]:
            rows = await connection.fetch(
                "SELECT * FROM recovery_ceremonies WHERE status = 'active'"
                " AND (ceremony_id = $1 OR recovery_key_id = $1)"
                " ORDER BY kind = 'resharing', closed_at, ceremony_id",
                key_id,
            )
            return [await snapshot_of(connection, row) for row in rows]

        return await _run(self._pool, tenant_id, work)


def _event(
    snapshot: CeremonySnapshot, actor: str, event_type: str, ref: str, now: datetime
) -> AuditEvent:
    return AuditEvent(snapshot.ceremony.tenant_id, actor, event_type, ref, now)


async def _abort_failed(
    connection: asyncpg.Connection,
    snapshot: CeremonySnapshot,
    events: Sequence[AuditEvent],
    now: datetime,
    reason: str,
) -> str:
    """Committed, not raised: the abort must outlive the confirmation that found it."""
    ceremony_id = snapshot.ceremony.ceremony_id
    await connection.execute(
        "UPDATE recovery_ceremonies SET status = 'aborted', closed_at = $2,"
        " close_reason = $3 WHERE ceremony_id = $1",
        ceremony_id,
        now,
        reason,
    )
    await clear_subshares(connection, [ceremony_id])
    aborted = _event(
        snapshot, SYSTEM_ACTOR, "ceremony_aborted", f"ceremony:{ceremony_id}:{reason}", now
    )
    await append_audits(connection, [*events, aborted])
    return "aborted"


async def _close_open_requests(
    connection: asyncpg.Connection, snapshot: CeremonySnapshot, now: datetime
) -> list[AuditEvent]:
    """No request spans two generations: approvals of the old holders cannot combine (§9.7)."""
    rows = await connection.fetch(
        "SELECT request_id, expires_at <= $1 AS lapsed FROM recovery_requests"
        " WHERE status = 'open' ORDER BY request_id FOR UPDATE",
        now,
    )
    if not rows:
        return []
    ids = [row["request_id"] for row in rows]
    # Shared and in order before the deletes, as the re-enrolment swap does against a shred.
    await connection.execute(
        "SELECT 1 FROM conversations c WHERE c.conversation_id IN ("
        " SELECT p.conversation_id FROM recovery_partials p WHERE p.request_id = ANY($1::uuid[]))"
        " ORDER BY c.conversation_id FOR SHARE",
        ids,
    )
    await connection.execute(
        "DELETE FROM recovery_partials WHERE request_id = ANY($1::uuid[])", ids
    )
    await connection.execute(
        "UPDATE recovery_requests SET closed_at = $2,"
        " status = CASE WHEN expires_at <= $2 THEN 'expired' ELSE 'cancelled' END"
        " WHERE request_id = ANY($1::uuid[])",
        ids,
        now,
    )
    return [
        _event(
            snapshot,
            SYSTEM_ACTOR,
            "recovery.request.expired" if row["lapsed"] else "recovery.request.cancelled",
            str(row["request_id"]),
            now,
        )
        for row in rows
    ]


async def _replace_shares(
    connection: asyncpg.Connection, snapshot: CeremonySnapshot, key_id: Any
) -> None:
    public = new_public_shares(snapshot)
    sealed = {c.holder_index: c.encrypted_share for c in snapshot.confirmations}
    ceremony = snapshot.ceremony
    await connection.execute("DELETE FROM recovery_shares WHERE key_id = $1", key_id)
    await connection.executemany(
        "INSERT INTO recovery_shares (tenant_id, key_id, holder_index, holder_ref,"
        " holder_public_share, encrypted_share, ceremony_id) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        [
            (
                ceremony.tenant_id,
                key_id,
                p.holder_index,
                p.holder_ref,
                public[p.holder_index],
                sealed.get(p.holder_index),
                ceremony.ceremony_id,
            )
            for p in snapshot.participants
        ],
    )


async def activate_resharing(
    connection: asyncpg.Connection, snapshot: CeremonySnapshot, events: Sequence[AuditEvent]
) -> str:
    """'active', or 'aborted' when the new shares do not rebuild X; the caller holds the ceremony."""
    ceremony = snapshot.ceremony
    now = events[-1].at
    key = await connection.fetchrow(
        "SELECT key_id, recovery_public_key, holders_transcript_hash FROM recovery_keys"
        " WHERE key_id = $1 AND status = 'active' FOR UPDATE",
        ceremony.recovery_key_id,
    )
    # The generation it replaces must still be the current one, or the old shares it
    # would delete are not the ones its dealers held.
    if key is None or bytes(key["holders_transcript_hash"]) != ceremony.previous_transcript_hash:
        return await _abort_failed(connection, snapshot, events, now, "chain_invalid")
    if not end_to_end_holds(snapshot, bytes(key["recovery_public_key"])):
        return await _abort_failed(connection, snapshot, events, now, "canary_failed")
    cancelled = await _close_open_requests(connection, snapshot, now)
    await _replace_shares(connection, snapshot, key["key_id"])
    await connection.execute(
        "UPDATE recovery_keys SET holders_ceremony_id = $2, holders_transcript_hash = $3,"
        " k = $4, n = $5, mode = $6 WHERE key_id = $1",
        key["key_id"],
        ceremony.ceremony_id,
        ceremony.transcript_hash,
        ceremony.k,
        len(snapshot.participants),
        "standard" if ceremony.k == 1 else "enhanced",
    )
    # No share a retired key opened is left, so the blobs kept for resharing go (§9.6).
    await connection.execute(
        "UPDATE user_keys SET encrypted_private = NULL"
        " WHERE retired_at IS NOT NULL AND encrypted_private IS NOT NULL"
    )
    await connection.execute(
        "UPDATE recovery_ceremonies SET status = 'active', closed_at = $2 WHERE ceremony_id = $1",
        ceremony.ceremony_id,
        now,
    )
    closed = await connection.fetch(
        "SELECT ceremony_id FROM recovery_ceremonies WHERE status <> ALL($1::text[])", list(OPEN)
    )
    await clear_subshares(connection, [row["ceremony_id"] for row in closed])
    reshared = _event(
        snapshot,
        events[-1].actor_sub,
        "recovery_key_reshared",
        f"recovery-key:{key['key_id']}:ceremony:{ceremony.ceremony_id}",
        now,
    )
    await append_audits(connection, [*events, *cancelled, reshared])
    return "active"
