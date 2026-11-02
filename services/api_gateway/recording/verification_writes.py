"""Closing verification records, shared by every writer that closes them (spec §10.7).

The notes trigger lets the app delete notes only while their record is in
review, so the notes go first; the freeze trigger then makes the closed record
final. Decline, retirement and revocation must all close the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import asyncpg

_DROP_NOTES = "DELETE FROM verification_notes WHERE verification_id = ANY($1::uuid[])"
_CLOSE = (
    "UPDATE verifications SET status = $2, closed_at = $3, close_reason = $4,"
    " overall_note = NULL WHERE verification_id = ANY($1::uuid[])"
)


async def close_records(
    connection: asyncpg.Connection,
    ids: Sequence[Any],
    status: str,
    reason: str,
    now: datetime,
) -> None:
    """`ids` must be locked by the caller; drafts are deleted before the status changes."""
    if not ids:
        return
    await connection.execute(_DROP_NOTES, list(ids))
    await connection.execute(_CLOSE, list(ids), status, now, reason)
