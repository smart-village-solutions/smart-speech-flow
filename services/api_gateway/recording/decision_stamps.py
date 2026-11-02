"""RFC 3161 tokens for verification decisions (spec §10.7, §11.2, A.3a).

The imprint is SHA-256 of the signed digest and the signature together, so
the token proves when this exact signature existed. Runs inside the chain
stamper's pass, over the same writer tenants and with the same back-off.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol

from ..clock import utc_now
from .archive_service import STAMP_RETRY_CEILING, STAMP_RETRY_INITIAL
from .crypto import tags
from .crypto.signatures import signed_digest
from .crypto.verification import decision_imprint, verification_fields
from .repository import RecordingStorageUnavailable
from .timestamps import TimestampAuthority, TimestampError
from .verification_model import PendingDecisionStamp

logger = logging.getLogger(__name__)


class DecisionStampStore(Protocol):
    async def pending_decision_stamps(
        self, tenant_id: str, now: datetime, limit: int = 20
    ) -> list[PendingDecisionStamp]: ...

    async def save_decision_stamp(
        self, tenant_id: str, stamp: PendingDecisionStamp, token: bytes, stamped_at: datetime
    ) -> None: ...

    async def defer_decision_stamp(
        self, tenant_id: str, stamp: PendingDecisionStamp, next_attempt_at: datetime
    ) -> None: ...


def imprint_of(tenant_id: str, stamp: PendingDecisionStamp) -> bytes:
    fields = verification_fields(
        tenant_id,
        stamp.verification_id,
        stamp.conversation_id,
        stamp.reviewed_head,
        stamp.outcome,
        stamp.notes_digest,
        stamp.permission_snapshot,
    )
    return decision_imprint(signed_digest(tags.VERIFICATION_SIG, *fields), stamp.signature)


class DecisionStamper:
    def __init__(
        self,
        store: DecisionStampStore,
        authority: TimestampAuthority,
        tenants: Callable[[], Iterable[str]],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._authority = authority
        self._tenants = tenants
        self._clock = clock

    async def run_once(self) -> None:
        for tenant_id in tuple(self._tenants()):
            try:
                due = await self._store.pending_decision_stamps(tenant_id, self._clock())
                for stamp in due:
                    await self._stamp(tenant_id, stamp)
            except RecordingStorageUnavailable:
                logger.warning("recording_decision_stamp_skipped")

    async def _stamp(self, tenant_id: str, stamp: PendingDecisionStamp) -> None:
        try:
            token = await self._authority.stamp(stamp.url, imprint_of(tenant_id, stamp))
        except Exception as error:  # one authority's answer must never stop the others
            code = error.code if isinstance(error, TimestampError) else type(error).__name__
            delay = min(STAMP_RETRY_INITIAL * (2**stamp.attempts), STAMP_RETRY_CEILING)
            logger.warning("recording_decision_stamp_deferred code=%s", code)
            await self._store.defer_decision_stamp(tenant_id, stamp, self._clock() + delay)
            return
        await self._store.save_decision_stamp(tenant_id, stamp, token.token, token.gen_time)
