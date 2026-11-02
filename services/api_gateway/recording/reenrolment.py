"""Re-enrolment: a new key pair for someone who lost their passphrase (spec §9.6).

The swap waits on a confirmation port. Its email adapter (§9.9) answers
"pending", keeps the new key aside, and the link's confirm runs the same swap.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ..clock import utc_now
from .key_confirmation_repository import PendingKey
from .keys import Enrolment, InvalidEnrolment, sealed_record, validate_enrolment
from .reenrolment_repository import ReenrolmentImpact
from .repository import RecordingStorageUnavailable, UserKeyRecord
from .secrets import ServerLayer


class Confirmation(Protocol):
    # False when it cannot confirm anything: the re-enrolment is refused before any work.
    available: bool

    async def request(self, record: UserKeyRecord, replaces_version: int) -> None:
        """Keeps the record aside and sends its confirmation; ReenrolmentError if refused.

        It re-checks the swap's refusals itself, under the key row's lock.
        """
        ...

    async def pending(self, tenant_id: str, sub: str, now: datetime) -> PendingKey | None: ...


class ReenrolmentStore(Protocol):
    async def impact(self, tenant_id: str, sub: str) -> ReenrolmentImpact: ...


@dataclass(frozen=True)
class Reenrolled:
    # A new key always waits for its mailed link (§9.9); confirm activates it.
    status: Literal["pending_confirmation"]
    fingerprint: bytes


class ReenrolmentError(Exception):
    """key_not_enrolled, key_changed, ceremony_in_progress, invalid, email_not_verified,
    mail_unavailable or unavailable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _guarded[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except RecordingStorageUnavailable:
        raise ReenrolmentError("unavailable") from None


class KeyReenrolment:
    def __init__(
        self,
        *,
        store: ReenrolmentStore,
        server_layer: ServerLayer,
        confirmation: Confirmation,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._server_layer = server_layer
        self._confirmation = confirmation
        self._clock = clock

    async def reenrol(
        self, tenant_id: str, user_sub: str, enrolment: Enrolment, replaces_version: int
    ) -> Reenrolled:
        if not self._confirmation.available:
            raise ReenrolmentError("mail_unavailable")
        try:
            validate_enrolment(enrolment)
        except InvalidEnrolment:
            raise ReenrolmentError("invalid") from None
        record = sealed_record(
            self._server_layer,
            tenant_id,
            user_sub,
            enrolment,
            version=replaces_version + 1,
            now=self._clock(),
        )
        # Never active at once: the key waits for its mailed link (§9.9).
        await _guarded(self._confirmation.request(record, replaces_version))
        return Reenrolled("pending_confirmation", record.fingerprint)

    async def impact(self, tenant_id: str, user_sub: str) -> ReenrolmentImpact:
        return await _guarded(self._store.impact(tenant_id, user_sub))

    async def pending(self, tenant_id: str, user_sub: str) -> PendingKey | None:
        """The key waiting for its link, if one is out (§9.9)."""
        return await _guarded(self._confirmation.pending(tenant_id, user_sub, self._clock()))
