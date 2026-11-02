"""§9.6's swap without its link, for tests only (spec §9.9).

Production swaps a key only through the mailed link's confirm. Tests that need
a re-enrolled key build it from the same steps confirm runs.
"""

from __future__ import annotations

from datetime import datetime

from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment_repository import (
    complete_swap,
    lock_active_key,
    reenrolment_refusal,
)
from services.api_gateway.recording.repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    UserKeyRecord,
    bind_tenant,
    storage_unavailable,
)


async def swap_key(
    pool, record: UserKeyRecord, replaces_version: int, now: datetime
) -> Refused | None:
    try:
        async with (
            pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection,
            connection.transaction(),
        ):
            await bind_tenant(connection, record.tenant_id)
            old = await lock_active_key(connection, record.user_sub)
            refused = await reenrolment_refusal(
                connection, old, record.user_sub, replaces_version, now
            )
            if refused is not None:
                return refused
            await complete_swap(connection, record, old, now, [])
            return None
    except DRIVER_FAILURE as error:
        raise storage_unavailable(error) from None
