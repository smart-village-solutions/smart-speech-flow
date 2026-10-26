"""Postgres access for the recovery-key ceremony (migration 002).

Every write takes the ceremony row FOR UPDATE and re-checks its status, so
two custodians submitting at once cannot both move it on, and a ceremony
aborted a moment ago accepts nothing more. Tenant isolation is row-level
security, as in repository.py.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

import asyncpg

from .audit import AuditEvent
from .ceremony_model import (
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    ConfirmationRecord,
    DealingRecord,
    RecoveryKeyRecord,
    RecoveryShareRecord,
    conflict,
)
from .crypto.encoding import b64url, from_b64url, scalar_from_bytes, scalar_to_bytes
from .repository import (
    DRIVER_FAILURE,
    PostgresRecordingRepository,
    UserKeyRecord,
    append_audit,
    bind_tenant,
    storage_unavailable,
    user_key_from_row,
)

_OPEN = ("dealing", "confirming")


def _gateway_keys_json(keys: Sequence[tuple[str, bytes]]) -> str:
    return json.dumps([[key_id, b64url(public)] for key_id, public in keys])


def _ceremony(row: Any) -> CeremonyRecord:
    keys = json.loads(row["gateway_keys"])
    transcript = row["transcript_hash"]
    return CeremonyRecord(
        tenant_id=row["tenant_id"],
        ceremony_id=str(row["ceremony_id"]),
        k=row["k"],
        started_by=row["started_by"],
        started_at=row["started_at"],
        expires_at=row["expires_at"],
        status=row["status"],
        gateway_keys=tuple((key_id, from_b64url(public)) for key_id, public in keys),
        transcript_hash=None if transcript is None else bytes(transcript),
        paper_confirmed_at=row["paper_confirmed_at"],
    )


def _participant(row: Any) -> CeremonyParticipant:
    sig_pub = row["sig_pub"]
    return CeremonyParticipant(
        holder_index=row["holder_index"],
        holder_ref=row["holder_ref"],
        kind=row["kind"],
        display_name=row["display_name"],
        enc_pub=bytes(row["enc_pub"]),
        sig_pub=None if sig_pub is None else bytes(sig_pub),
        fingerprint=bytes(row["fingerprint"]),
    )


def _dealing(row: Any) -> DealingRecord:
    return DealingRecord(
        dealer_index=row["dealer_index"],
        commitments=tuple(bytes(item) for item in row["commitments"]),
        proof_c=scalar_from_bytes(bytes(row["proof_c"])),
        proof_s=scalar_from_bytes(bytes(row["proof_s"])),
        signature=bytes(row["signature"]),
        dealt_at=row["dealt_at"],
        subshares={},
    )


def _confirmation(row: Any) -> ConfirmationRecord:
    return ConfirmationRecord(
        holder_index=row["holder_index"],
        transcript_signature=bytes(row["transcript_signature"]),
        encrypted_share=row["encrypted_share"],
        confirmed_at=row["confirmed_at"],
    )


def _recovery_key(row: Any) -> RecoveryKeyRecord:
    return RecoveryKeyRecord(
        tenant_id=row["tenant_id"],
        key_id=str(row["key_id"]),
        recovery_public_key=bytes(row["recovery_public_key"]),
        k=row["k"],
        n=row["n"],
        mode=row["mode"],
        transcript_hash=bytes(row["transcript_hash"]),
        canary_wrap=row["canary_wrap"],
        canary_signature=bytes(row["canary_signature"]),
        canary_signer_key_id=row["canary_signer_key_id"],
        activated_at=row["activated_at"],
    )


async def _lock(
    connection: asyncpg.Connection, ceremony_id: str, now: datetime, statuses: Collection[str]
) -> asyncpg.Record:
    row = await connection.fetchrow(
        "SELECT * FROM recovery_ceremonies WHERE ceremony_id = $1 FOR UPDATE", ceremony_id
    )
    if row is None:
        raise conflict("NO_CEREMONY", "No such ceremony")
    if row["status"] not in statuses or row["expires_at"] <= now:
        raise conflict("CEREMONY_STATE", "The ceremony does not accept this step now")
    return row


async def _snapshot(connection: asyncpg.Connection, row: Any) -> CeremonySnapshot:
    ceremony_id = row["ceremony_id"]
    participants = await connection.fetch(
        "SELECT * FROM ceremony_participants WHERE ceremony_id = $1 ORDER BY holder_index",
        ceremony_id,
    )
    dealings = await connection.fetch(
        "SELECT dealer_index, commitments, proof_c, proof_s, signature, dealt_at"
        " FROM ceremony_dealings WHERE ceremony_id = $1 ORDER BY dealer_index",
        ceremony_id,
    )
    confirmations = await connection.fetch(
        "SELECT * FROM ceremony_confirmations WHERE ceremony_id = $1 ORDER BY holder_index",
        ceremony_id,
    )
    return CeremonySnapshot(
        ceremony=_ceremony(row),
        participants=tuple(_participant(item) for item in participants),
        dealings=tuple(_dealing(item) for item in dealings),
        confirmations=tuple(_confirmation(item) for item in confirmations),
    )


class PostgresCeremonyRepository(PostgresRecordingRepository):
    """The recording repository plus the ceremony tables; one pool serves both."""

    async def _read(self, tenant_id: str, query: str, *args: Any) -> list[asyncpg.Record]:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    return list(await connection.fetch(query, *args))
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None:
        rows = await self._read(tenant_id, "SELECT * FROM recovery_keys WHERE status = 'active'")
        return _recovery_key(rows[0]) if rows else None

    async def recovery_shares(self, tenant_id: str, key_id: str) -> list[RecoveryShareRecord]:
        rows = await self._read(
            tenant_id,
            "SELECT * FROM recovery_shares WHERE key_id = $1 ORDER BY holder_index",
            key_id,
        )
        return [
            RecoveryShareRecord(
                holder_index=row["holder_index"],
                holder_ref=row["holder_ref"],
                holder_public_share=bytes(row["holder_public_share"]),
                encrypted_share=row["encrypted_share"],
            )
            for row in rows
        ]

    async def user_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, UserKeyRecord]:
        rows = await self._read(
            tenant_id,
            "SELECT * FROM user_keys WHERE user_sub = ANY($1::text[]) AND retired_at IS NULL",
            list(subs),
        )
        return {row["user_sub"]: user_key_from_row(row) for row in rows}

    async def open_ceremony(self, tenant_id: str, now: datetime) -> CeremonySnapshot | None:
        """The ceremony in progress; an expired one counts as over."""
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    row = await connection.fetchrow(
                        "SELECT * FROM recovery_ceremonies"
                        " WHERE status = ANY($1::text[]) AND expires_at > $2",
                        list(_OPEN),
                        now,
                    )
                    return None if row is None else await _snapshot(connection, row)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def subshares_for(
        self, tenant_id: str, ceremony_id: str, recipients: Collection[int]
    ) -> dict[int, dict[int, str]]:
        """Recipient index -> dealer index -> sealed sub-share, for these recipients only."""
        rows = await self._read(
            tenant_id,
            "SELECT dealer_index, subshares FROM ceremony_dealings WHERE ceremony_id = $1",
            ceremony_id,
        )
        received: dict[int, dict[int, str]] = {index: {} for index in recipients}
        for row in rows:
            sealed = json.loads(row["subshares"])
            for index in recipients:
                received[index][row["dealer_index"]] = sealed[str(index)]
        return received

    async def create_ceremony(
        self,
        ceremony: CeremonyRecord,
        participants: Sequence[CeremonyParticipant],
        audit: Sequence[AuditEvent],
    ) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, ceremony.tenant_id)
                    await self._insert_ceremony(connection, ceremony, participants)
                    for event in audit:
                        await append_audit(connection, event)
        except asyncpg.UniqueViolationError:
            raise conflict("CEREMONY_IN_PROGRESS", "A ceremony is already in progress") from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def _insert_ceremony(
        self,
        connection: asyncpg.Connection,
        ceremony: CeremonyRecord,
        participants: Sequence[CeremonyParticipant],
    ) -> None:
        active = await connection.fetchval(
            "SELECT count(*) FROM recovery_keys WHERE status = 'active'"
        )
        if active:
            raise conflict("RECOVERY_KEY_EXISTS", "The tenant already has a recovery key")
        await connection.execute(
            "UPDATE recovery_ceremonies SET status = 'aborted', close_reason = 'expired',"
            " closed_at = $1 WHERE status = ANY($2::text[]) AND expires_at <= $1",
            ceremony.started_at,
            list(_OPEN),
        )
        await connection.execute(
            "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by,"
            " started_at, expires_at, status, gateway_keys)"
            " VALUES ($1, $2, $3, $4, $5, $6, 'dealing', $7)",
            ceremony.tenant_id,
            ceremony.ceremony_id,
            ceremony.k,
            ceremony.started_by,
            ceremony.started_at,
            ceremony.expires_at,
            _gateway_keys_json(ceremony.gateway_keys),
        )
        await connection.executemany(
            "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index,"
            " holder_ref, kind, display_name, enc_pub, sig_pub, fingerprint)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            [
                (
                    ceremony.tenant_id,
                    ceremony.ceremony_id,
                    p.holder_index,
                    p.holder_ref,
                    p.kind,
                    p.display_name,
                    p.enc_pub,
                    p.sig_pub,
                    p.fingerprint,
                )
                for p in participants
            ],
        )

    async def add_dealing(
        self, tenant_id: str, ceremony_id: str, dealing: DealingRecord, audit: AuditEvent
    ) -> CeremonySnapshot:
        """Returns the ceremony as it stands after this dealing."""
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    row = await _lock(connection, ceremony_id, dealing.dealt_at, ("dealing",))
                    await connection.execute(
                        "INSERT INTO ceremony_dealings (tenant_id, ceremony_id, dealer_index,"
                        " commitments, proof_c, proof_s, signature, subshares, dealt_at)"
                        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                        tenant_id,
                        ceremony_id,
                        dealing.dealer_index,
                        list(dealing.commitments),
                        scalar_to_bytes(dealing.proof_c),
                        scalar_to_bytes(dealing.proof_s),
                        dealing.signature,
                        json.dumps({str(i): sealed for i, sealed in dealing.subshares.items()}),
                        dealing.dealt_at,
                    )
                    await append_audit(connection, audit)
                    return await _snapshot(connection, row)
        except asyncpg.UniqueViolationError:
            raise conflict("ALREADY_SUBMITTED", "This custodian has already dealt") from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def begin_confirming(
        self, tenant_id: str, ceremony_id: str, transcript_hash: bytes, audit: AuditEvent
    ) -> None:
        """Dealing -> confirming. A second caller finds the move made and changes nothing."""
        await self._transition(
            tenant_id,
            "UPDATE recovery_ceremonies SET status = 'confirming', transcript_hash = $2"
            " WHERE ceremony_id = $1 AND status = 'dealing'",
            (ceremony_id, transcript_hash),
            audit,
        )

    async def add_confirmation(
        self,
        tenant_id: str,
        ceremony_id: str,
        confirmation: ConfirmationRecord,
        audit: AuditEvent,
    ) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    await _lock(connection, ceremony_id, confirmation.confirmed_at, ("confirming",))
                    await connection.execute(
                        "INSERT INTO ceremony_confirmations (tenant_id, ceremony_id,"
                        " holder_index, transcript_signature, encrypted_share, confirmed_at)"
                        " VALUES ($1, $2, $3, $4, $5, $6)",
                        tenant_id,
                        ceremony_id,
                        confirmation.holder_index,
                        confirmation.transcript_signature,
                        confirmation.encrypted_share,
                        confirmation.confirmed_at,
                    )
                    await append_audit(connection, audit)
        except asyncpg.UniqueViolationError:
            raise conflict("ALREADY_SUBMITTED", "This custodian has already confirmed") from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def confirm_paper(self, tenant_id: str, ceremony_id: str, audit: AuditEvent) -> None:
        await self._locked_update(
            tenant_id,
            ceremony_id,
            audit,
            "UPDATE recovery_ceremonies SET paper_confirmed_at = $2 WHERE ceremony_id = $1",
            ("confirming",),
        )

    async def abort(self, tenant_id: str, ceremony_id: str, reason: str, audit: AuditEvent) -> None:
        await self._locked_update(
            tenant_id,
            ceremony_id,
            audit,
            "UPDATE recovery_ceremonies SET status = 'aborted', closed_at = $2,"
            " close_reason = $3 WHERE ceremony_id = $1",
            _OPEN,
            reason,
        )

    async def activate(
        self,
        tenant_id: str,
        key: RecoveryKeyRecord,
        shares: Sequence[RecoveryShareRecord],
        audit: AuditEvent,
    ) -> bool:
        """Confirming -> active with its key and shares. False if another caller got there first."""
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    moved = await connection.execute(
                        "UPDATE recovery_ceremonies SET status = 'active', closed_at = $2"
                        " WHERE ceremony_id = $1 AND status = 'confirming'",
                        key.key_id,
                        key.activated_at,
                    )
                    if moved != "UPDATE 1":
                        return False
                    await self._insert_key(connection, key, shares)
                    await append_audit(connection, audit)
                    return True
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def _insert_key(
        self,
        connection: asyncpg.Connection,
        key: RecoveryKeyRecord,
        shares: Sequence[RecoveryShareRecord],
    ) -> None:
        await connection.execute(
            "INSERT INTO recovery_keys (tenant_id, key_id, recovery_public_key, k, n, mode,"
            " transcript_hash, canary_wrap, canary_signature, canary_signer_key_id, status,"
            " activated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active', $11)",
            key.tenant_id,
            key.key_id,
            key.recovery_public_key,
            key.k,
            key.n,
            key.mode,
            key.transcript_hash,
            key.canary_wrap,
            key.canary_signature,
            key.canary_signer_key_id,
            key.activated_at,
        )
        await connection.executemany(
            "INSERT INTO recovery_shares (tenant_id, key_id, holder_index, holder_ref,"
            " holder_public_share, encrypted_share) VALUES ($1, $2, $3, $4, $5, $6)",
            [
                (
                    key.tenant_id,
                    key.key_id,
                    share.holder_index,
                    share.holder_ref,
                    share.holder_public_share,
                    share.encrypted_share,
                )
                for share in shares
            ],
        )

    async def _transition(
        self, tenant_id: str, query: str, args: tuple[Any, ...], audit: AuditEvent
    ) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    if await connection.execute(query, *args) == "UPDATE 1":
                        await append_audit(connection, audit)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def _locked_update(
        self,
        tenant_id: str,
        ceremony_id: str,
        audit: AuditEvent,
        query: str,
        statuses: Collection[str],
        *extra: Any,
    ) -> None:
        """Run `query` with ($1 ceremony_id, $2 audit time, *extra) under the ceremony lock."""
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    await _lock(connection, ceremony_id, audit.at, statuses)
                    await connection.execute(query, ceremony_id, audit.at, *extra)
                    await append_audit(connection, audit)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
