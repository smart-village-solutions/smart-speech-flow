"""Row mapping and shared steps for the ceremony tables (migrations 002, 008).

Both the first ceremony's repository and the resharing's use these, so a
snapshot reads the same way, and a closed ceremony loses its sub-shares the
same way, whichever kind it is.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

import asyncpg

from .ceremony_model import (
    CeremonyDealer,
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    ConfirmationRecord,
    DealingRecord,
    RecoveryKeyRecord,
    conflict,
)
from .crypto.encoding import b64url, from_b64url, scalar_from_bytes

OPEN = ("dealing", "confirming")


def gateway_keys_json(keys: Sequence[tuple[str, bytes]]) -> str:
    return json.dumps([[key_id, b64url(public)] for key_id, public in keys])


def ceremony_row(row: Any) -> CeremonyRecord:
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
        kind=row["kind"],
        recovery_key_id=None if row["recovery_key_id"] is None else str(row["recovery_key_id"]),
        previous_transcript_hash=_optional_bytes(row["previous_transcript_hash"]),
    )


def _optional_bytes(value: Any) -> bytes | None:
    return None if value is None else bytes(value)


def participant_row(row: Any) -> CeremonyParticipant:
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
        signature=_optional_bytes(row["signature"]),
        dealt_at=row["dealt_at"],
        subshares={},
    )


def _confirmation(row: Any) -> ConfirmationRecord:
    return ConfirmationRecord(
        holder_index=row["holder_index"],
        transcript_signature=bytes(row["transcript_signature"]),
        encrypted_share=row["encrypted_share"],
        confirmed_at=row["confirmed_at"],
        share_proof=(
            None
            if row["share_proof_c"] is None
            else (
                scalar_from_bytes(bytes(row["share_proof_c"])),
                scalar_from_bytes(bytes(row["share_proof_s"])),
            )
        ),
    )


def recovery_key_row(row: Any) -> RecoveryKeyRecord:
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
        holders_ceremony_id=str(row["holders_ceremony_id"]),
        holders_transcript_hash=bytes(row["holders_transcript_hash"]),
    )


async def lock_ceremony(
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


async def snapshot_of(connection: asyncpg.Connection, row: Any) -> CeremonySnapshot:
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
    dealers = await connection.fetch(
        "SELECT dealer_index, holder_ref, kind FROM ceremony_dealers WHERE ceremony_id = $1"
        " ORDER BY dealer_index",
        ceremony_id,
    )
    return CeremonySnapshot(
        ceremony=ceremony_row(row),
        participants=tuple(participant_row(item) for item in participants),
        dealings=tuple(_dealing(item) for item in dealings),
        confirmations=tuple(_confirmation(item) for item in confirmations),
        dealers=tuple(
            CeremonyDealer(item["dealer_index"], item["holder_ref"], item["kind"])
            for item in dealers
        ),
    )


async def insert_holders(
    connection: asyncpg.Connection,
    ceremony: CeremonyRecord,
    participants: Sequence[CeremonyParticipant],
    dealers: Sequence[CeremonyDealer],
) -> None:
    """A ceremony's new holders, and who deals to them."""
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
    await connection.executemany(
        "INSERT INTO ceremony_dealers (tenant_id, ceremony_id, dealer_index, holder_ref, kind)"
        " VALUES ($1, $2, $3, $4, $5)",
        [
            (ceremony.tenant_id, ceremony.ceremony_id, d.dealer_index, d.holder_ref, d.kind)
            for d in dealers
        ],
    )


async def close_lapsed(connection: asyncpg.Connection, now: datetime) -> None:
    """A ceremony past its time is over; its sub-shares go with it (§9.7)."""
    lapsed = await connection.fetch(
        "UPDATE recovery_ceremonies SET status = 'aborted', close_reason = 'expired',"
        " closed_at = $1 WHERE status = ANY($2::text[]) AND expires_at <= $1"
        " RETURNING ceremony_id",
        now,
        list(OPEN),
    )
    await clear_subshares(connection, [row["ceremony_id"] for row in lapsed])


async def clear_subshares(connection: asyncpg.Connection, ceremony_ids: Sequence[Any]) -> None:
    """A closed ceremony's sub-shares are a complete sharing nobody needs any more."""
    if ceremony_ids:
        await connection.execute(
            "UPDATE ceremony_dealings SET subshares = '{}'::jsonb"
            " WHERE ceremony_id = ANY($1::uuid[]) AND subshares <> '{}'::jsonb",
            list(ceremony_ids),
        )
