"""The email confirmation adapter: hold, then mail, release on failure (spec §9.9)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.crypto.transcript import display_fingerprint
from services.api_gateway.recording.key_confirmation_repository import PendingKey
from services.api_gateway.recording.mail import MailError
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment import ReenrolmentError
from services.api_gateway.recording.reenrolment_email import (
    LINK_LIFETIME,
    EmailConfirmation,
    compose,
    token_hash,
)
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord
from tests import recording_crypto_reference as ref

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
ORIGIN = "https://dialog.example.org"
TOKEN = bytes(range(32))
RECORD = UserKeyRecord(
    tenant_id="tenant-a",
    user_sub="alice",
    key_version=3,
    enc_pub=ref.public_point(7),
    sig_pub=ref.public_point(8),
    fingerprint=b"\x05" * 32,
    encrypted_private=b"sealed",
    created_at=NOW,
)


class FakeStore:
    def __init__(self, held: Refused | str = "alice@example.org") -> None:
        self.held = held
        self.calls: list[tuple] = []

    async def sweep(self, tenant_id, now, *, keep=None):
        self.calls.append(("sweep", tenant_id, now, keep))

    async def hold(self, record, replaces_version, hashed, expires_at):
        self.calls.append(("hold", record.user_sub, replaces_version, hashed, expires_at))
        return self.held

    async def release(self, tenant_id, hashed, now):
        self.calls.append(("release", tenant_id, hashed, now))

    async def pending_of(self, tenant_id, sub, now):
        self.calls.append(("pending_of", tenant_id, sub, now))
        return PendingKey(b"\x05" * 32, NOW + LINK_LIFETIME)


class FakeMailer:
    def __init__(self, error: MailError | None = None) -> None:
        self.error = error
        self.sent: list = []

    async def send(self, message):
        self.sent.append(message)
        if self.error is not None:
            raise self.error


def _adapter(store, mailer=None, origin=ORIGIN):
    return EmailConfirmation(
        store=store, mailer=mailer, origin=origin, token=lambda size: TOKEN[:size]
    )


async def test_the_key_is_held_first_then_mailed_to_the_pinned_address():
    store, mailer = FakeStore(), FakeMailer()

    await _adapter(store, mailer).request(RECORD, 2)

    hashed = hashlib.sha256(TOKEN).digest()
    assert store.calls == [
        ("sweep", "tenant-a", NOW, None),
        ("hold", "alice", 2, hashed, NOW + timedelta(minutes=30)),
    ]
    [message] = mailer.sent
    assert message.to == "alice@example.org"
    assert f"{ORIGIN}/key-confirmation#{b64url(TOKEN)}" in message.body
    assert len(b64url(TOKEN)) == 43


async def test_a_refused_hold_sends_nothing():
    store, mailer = FakeStore(Refused("email_not_verified")), FakeMailer()
    with pytest.raises(ReenrolmentError, match="email_not_verified"):
        await _adapter(store, mailer).request(RECORD, 2)
    assert mailer.sent == []


async def test_a_failed_mail_releases_its_own_pending_key():
    store = FakeStore()
    with pytest.raises(ReenrolmentError, match="mail_unavailable"):
        await _adapter(store, FakeMailer(MailError("OSError"))).request(RECORD, 2)
    assert store.calls[-1] == ("release", "tenant-a", token_hash(TOKEN), NOW)


@pytest.mark.parametrize(("mailer", "origin"), [(None, ORIGIN), (FakeMailer(), None)])
async def test_without_a_mailer_or_an_origin_it_is_unavailable(mailer, origin):
    store = FakeStore()
    adapter = _adapter(store, mailer, origin)
    assert adapter.available is False
    with pytest.raises(ReenrolmentError, match="mail_unavailable"):
        await adapter.request(RECORD, 2)
    assert store.calls == []


async def test_the_pending_key_is_only_read():
    """Review: the keys screen's read must not write; the next request sweeps."""
    store = FakeStore()
    pending = await _adapter(store, FakeMailer()).pending("tenant-a", "alice", NOW)
    assert pending == PendingKey(b"\x05" * 32, NOW + LINK_LIFETIME)
    assert [call[0] for call in store.calls] == ["pending_of"]


async def test_a_failed_release_still_answers_that_mail_is_unavailable():
    class StuckStore(FakeStore):
        async def release(self, tenant_id, hashed, now):
            raise RecordingStorageUnavailable("down")

    with pytest.raises(ReenrolmentError, match="mail_unavailable"):
        await _adapter(StuckStore(), FakeMailer(MailError("OSError"))).request(RECORD, 2)


def test_the_mail_holds_link_fingerprint_and_both_languages_and_no_sub():
    fingerprint = display_fingerprint(b"\x05" * 32)
    message = compose(
        "alice@example.org", f"{ORIGIN}/key-confirmation#abc", fingerprint, NOW, NOW + LINK_LIFETIME
    )

    assert message.subject == "Neuen Schlüssel bestätigen / Confirm your new key"
    assert message.to == "alice@example.org"
    for text in (f"{ORIGIN}/key-confirmation#abc", fingerprint, "2026-11-02 09:30 UTC"):
        assert text in message.body
    assert "Das war ich nicht" in message.body and "This wasn't me" in message.body
    assert message.body.index("Guten Tag") < message.body.index("Hello")
    assert "alice" not in message.body.replace("alice@example.org", "")
