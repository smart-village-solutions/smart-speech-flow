"""The email confirmation of a re-enrolment (spec §9.9).

The new key is held aside and its link mailed to the address pinned on the key
it replaces. The mail goes out after the hold commits, never inside it; if it
cannot go out, the hold is released by its own token, never a newer one.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final, Protocol

from .crypto.encoding import b64url
from .crypto.transcript import display_fingerprint
from .key_confirmation_repository import PendingKey
from .mail import Mailer, MailError, MailMessage
from .recovery_requests_model import Refused
from .reenrolment import ReenrolmentError
from .repository import RecordingStorageUnavailable, UserKeyRecord

LINK_LIFETIME: Final[timedelta] = timedelta(minutes=30)
TOKEN_BYTES: Final[int] = 32
SUBJECT: Final[str] = "Neuen Schlüssel bestätigen / Confirm your new key"

_BODY: Final[str] = """Guten Tag,

für Ihr Konto wurde am {at} ein neuer persönlicher Schlüssel angefordert.
Er wird erst aktiv, wenn Sie ihn über diesen Link bestätigen:

{link}

Fingerabdruck des neuen Schlüssels:
{fingerprint}

Der Link gilt nur einmal und nur bis {until}.

Waren Sie das nicht? Öffnen Sie den Link, wählen Sie „Das war ich nicht“
und informieren Sie Ihre Administration.

---

Hello,

a new personal key was requested for your account on {at}.
It becomes active only once you confirm it through this link:

{link}

Fingerprint of the new key:
{fingerprint}

The link works once, and only until {until}.

Not you? Open the link, choose "This wasn't me" and tell your administrator.
"""


class PendingStore(Protocol):
    async def sweep(self, tenant_id: str, now: datetime, *, keep: bytes | None = None) -> None: ...

    async def hold(
        self,
        record: UserKeyRecord,
        replaces_version: int,
        token_hash: bytes,
        expires_at: datetime,
    ) -> Refused | str: ...

    async def release(self, tenant_id: str, token_hash: bytes, now: datetime) -> None: ...

    async def pending_of(self, tenant_id: str, sub: str, now: datetime) -> PendingKey | None: ...


def token_hash(token: bytes) -> bytes:
    return hashlib.sha256(token).digest()


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def compose(
    to: str, link: str, fingerprint: str, requested_at: datetime, expires_at: datetime
) -> MailMessage:
    body = _BODY.format(
        at=_utc(requested_at), link=link, fingerprint=fingerprint, until=_utc(expires_at)
    )
    return MailMessage(to, SUBJECT, body)


class EmailConfirmation:
    def __init__(
        self,
        *,
        store: PendingStore,
        mailer: Mailer | None,
        origin: str | None,
        token: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self._store = store
        self._mailer = mailer
        self._origin = origin
        self._token = token
        self.available = mailer is not None and origin is not None

    async def request(self, record: UserKeyRecord, replaces_version: int) -> None:
        """Holds the key and mails its link; ReenrolmentError for every refusal."""
        if self._mailer is None or self._origin is None:
            raise ReenrolmentError("mail_unavailable")
        now = record.created_at
        await self._store.sweep(record.tenant_id, now)
        token = self._token(TOKEN_BYTES)
        hashed = token_hash(token)
        expires_at = now + LINK_LIFETIME
        held = await self._store.hold(record, replaces_version, hashed, expires_at)
        if isinstance(held, Refused):
            raise ReenrolmentError(held.code)
        link = f"{self._origin}/key-confirmation#{b64url(token)}"
        message = compose(held, link, display_fingerprint(record.fingerprint), now, expires_at)
        try:
            await self._mailer.send(message)
        except MailError as error:
            sys.stderr.write(f"Re-enrolment mail failed: {error}\n")
            await self._release(record.tenant_id, hashed, now)
            raise ReenrolmentError("mail_unavailable") from None

    async def _release(self, tenant_id: str, hashed: bytes, now: datetime) -> None:
        try:
            await self._store.release(tenant_id, hashed, now)
        except RecordingStorageUnavailable:
            # The hold outlives its unsent mail until a new request or its expiry ends it.
            sys.stderr.write("Re-enrolment hold could not be released\n")

    async def pending(self, tenant_id: str, sub: str, now: datetime) -> PendingKey | None:
        # A read: a lapsed link reads as none, and its audit is left to the next write.
        return await self._store.pending_of(tenant_id, sub, now)
