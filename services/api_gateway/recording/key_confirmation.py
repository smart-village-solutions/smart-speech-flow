"""The mailed link of a re-enrolment: look it up, confirm it or decline it (spec §9.9).

Nobody is logged in here. The token is the only authority: it names its tenant
through the database, and its row names the one user it acts for.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, TypeVar

from ..clock import utc_now
from .crypto.encoding import from_b64url
from .key_confirmation_repository import LinkDetails
from .recovery_requests_model import Refused
from .reenrolment_email import TOKEN_BYTES, token_hash
from .repository import RecordingStorageUnavailable

T = TypeVar("T")


class LinkStore(Protocol):
    async def tenant_of(self, token_hash: bytes) -> str | None: ...

    async def sweep(self, tenant_id: str, now: datetime, *, keep: bytes | None = None) -> None: ...

    async def lookup(
        self, tenant_id: str, token_hash: bytes, now: datetime
    ) -> LinkDetails | Refused: ...

    async def confirm(
        self, tenant_id: str, token_hash: bytes, now: datetime
    ) -> Refused | bytes: ...

    async def decline(self, tenant_id: str, token_hash: bytes, now: datetime) -> Refused | None: ...


class KeyConfirmationError(Exception):
    """link_invalid, link_expired, ceremony_in_progress or unavailable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _hashed(token: str) -> bytes:
    try:
        raw = from_b64url(token)
    except ValueError:
        raise KeyConfirmationError("link_invalid") from None
    if len(raw) != TOKEN_BYTES:
        raise KeyConfirmationError("link_invalid")
    return token_hash(raw)


class KeyConfirmations:
    def __init__(self, *, store: LinkStore, clock: Callable[[], datetime] = utc_now) -> None:
        self._store = store
        self._clock = clock

    async def _answer(
        self, token: str, act: Callable[[str, bytes, datetime], Awaitable[T | Refused]]
    ) -> T:
        hashed = _hashed(token)
        now = self._clock()
        try:
            tenant_id = await self._store.tenant_of(hashed)
            if tenant_id is None:
                raise KeyConfirmationError("link_invalid")
            # Its own transaction first; this link's own expiry is the call's to report.
            await self._store.sweep(tenant_id, now, keep=hashed)
            answer = await act(tenant_id, hashed, now)
        except RecordingStorageUnavailable:
            raise KeyConfirmationError("unavailable") from None
        if isinstance(answer, Refused):
            raise KeyConfirmationError(answer.code)
        return answer

    async def lookup(self, token: str) -> LinkDetails:
        return await self._answer(token, self._store.lookup)

    async def confirm(self, token: str) -> bytes:
        """The new key's fingerprint, once it replaced the old one."""
        return await self._answer(token, self._store.confirm)

    async def decline(self, token: str) -> None:
        await self._answer(token, self._store.decline)
