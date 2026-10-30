"""Re-enrolment: a new key pair for someone who lost their passphrase (spec §9.6).

The swap waits on a confirmation port. Today it confirms at once; the one-time
email link of spec §9.4 plugs in as another adapter, which answers "pending",
keeps the new key aside and runs the same swap when the link is opened.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ..clock import utc_now
from .keys import Enrolment, InvalidEnrolment, sealed_record, validate_enrolment
from .recovery_requests_model import Refused
from .reenrolment_repository import ReenrolmentImpact
from .repository import RecordingStorageUnavailable, UserKeyRecord
from .secrets import ServerLayer


class Confirmation(Protocol):
    async def request(self, record: UserKeyRecord, replaces_version: int) -> bool:
        """True to swap now; False once the record is kept aside and its confirmation sent.

        An email adapter stores `record` with `replaces_version`, and its confirm route
        runs the same swap once the link is opened.
        """
        ...


class ImmediateConfirmation:
    """Until mail delivery exists: step-up alone confirms (the email issue, before #620)."""

    async def request(self, record: UserKeyRecord, replaces_version: int) -> bool:
        return True


class ReenrolmentStore(Protocol):
    async def check(
        self, tenant_id: str, sub: str, replaces_version: int, now: datetime
    ) -> Refused | None: ...

    async def swap(
        self, record: UserKeyRecord, replaces_version: int, now: datetime
    ) -> Refused | None: ...

    async def impact(self, tenant_id: str, sub: str) -> ReenrolmentImpact: ...


@dataclass(frozen=True)
class Reenrolled:
    status: Literal["active", "pending_confirmation"]
    fingerprint: bytes


class ReenrolmentError(Exception):
    """key_not_enrolled, key_changed, ceremony_in_progress, invalid or unavailable."""

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
        # Refused before anything is sent: no confirmation for a version already replaced.
        refused = await _guarded(
            self._store.check(tenant_id, user_sub, replaces_version, record.created_at)
        )
        if refused is not None:
            raise ReenrolmentError(refused.code)
        if not await self._confirmation.request(record, replaces_version):
            return Reenrolled("pending_confirmation", record.fingerprint)
        refused = await _guarded(self._store.swap(record, replaces_version, record.created_at))
        if refused is not None:
            raise ReenrolmentError(refused.code)
        return Reenrolled("active", record.fingerprint)

    async def impact(self, tenant_id: str, user_sub: str) -> ReenrolmentImpact:
        return await _guarded(self._store.impact(tenant_id, user_sub))
