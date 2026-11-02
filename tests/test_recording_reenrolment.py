"""Re-enrolment holds the new key for its confirmation link (spec §9.6, §9.9)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.keys import Enrolment
from services.api_gateway.recording.key_confirmation_repository import PendingKey
from services.api_gateway.recording.reenrolment import KeyReenrolment, ReenrolmentError
from services.api_gateway.recording.reenrolment_repository import ReenrolmentImpact
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.secrets import ServerLayer
from tests import recording_crypto_reference as ref
from tests.recording_fakes import sealed_blob

TENANT = "tenant-a"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
ENROLMENT = Enrolment(ref.public_point(7), ref.public_point(8), sealed_blob())


class FakeStore:
    def __init__(self, error: BaseException | None = None):
        self.error = error

    async def impact(self, tenant_id, sub):
        if self.error is not None:
            raise self.error
        return ReenrolmentImpact(True, 2, 1)


class Pending:
    available = True

    def __init__(self, error: BaseException | None = None) -> None:
        self.asked: list = []
        self.error = error

    async def request(self, record, replaces_version):
        self.asked.append((record, replaces_version))
        if self.error is not None:
            raise self.error

    async def pending(self, tenant_id, sub, now):
        if self.error is not None:
            raise self.error
        return PendingKey(bytes(32), now)


class Unavailable(Pending):
    available = False


def _service(store, confirmation=None):
    return KeyReenrolment(
        store=store,
        server_layer=ServerLayer(os.urandom(32)),
        confirmation=confirmation or Pending(),
        clock=lambda: NOW,
    )


async def test_a_re_enrolment_holds_the_sealed_next_version_and_answers_pending():
    pending = Pending()

    done = await _service(FakeStore(), pending).reenrol(TENANT, "alice", ENROLMENT, 3)

    [(record, replaces)] = pending.asked
    assert (record.tenant_id, record.user_sub, record.key_version, replaces) == (
        TENANT,
        "alice",
        4,
        3,
    )
    assert record.created_at == NOW and record.encrypted_private != ENROLMENT.blob.encode()
    expected = fingerprint(TENANT, "alice", ENROLMENT.enc_pub, ENROLMENT.sig_pub)
    assert (done.status, done.fingerprint) == ("pending_confirmation", expected)


@pytest.mark.parametrize(
    "code", ["key_not_enrolled", "key_changed", "ceremony_in_progress", "email_not_verified"]
)
async def test_each_refusal_of_the_port_passes_through(code):
    with pytest.raises(ReenrolmentError, match=code):
        await _service(FakeStore(), Pending(ReenrolmentError(code))).reenrol(
            TENANT, "alice", ENROLMENT, 1
        )


async def test_an_invalid_body_is_refused_before_the_port_is_asked():
    pending = Pending()
    bad = Enrolment(ref.public_point(7), ref.public_point(7), sealed_blob())
    with pytest.raises(ReenrolmentError, match="invalid"):
        await _service(FakeStore(), pending).reenrol(TENANT, "alice", bad, 1)
    assert pending.asked == []


async def test_a_storage_failure_is_unavailable():
    failing = FakeStore(error=RecordingStorageUnavailable("down"))
    with pytest.raises(ReenrolmentError, match="unavailable"):
        await _service(failing).impact(TENANT, "alice")


async def test_the_impact_is_the_stores():
    assert await _service(FakeStore()).impact(TENANT, "carol") == ReenrolmentImpact(True, 2, 1)


async def test_without_mail_a_re_enrolment_is_refused_before_anything_is_checked():
    pending, store = Unavailable(), FakeStore()
    bad = Enrolment(ref.public_point(7), ref.public_point(7), sealed_blob())
    with pytest.raises(ReenrolmentError, match="mail_unavailable"):
        await _service(store, pending).reenrol(TENANT, "alice", bad, 1)
    assert pending.asked == []


async def test_a_storage_failure_while_holding_is_unavailable():
    pending = Pending(RecordingStorageUnavailable("down"))
    with pytest.raises(ReenrolmentError, match="unavailable"):
        await _service(FakeStore(), pending).reenrol(TENANT, "alice", ENROLMENT, 1)
    with pytest.raises(ReenrolmentError, match="unavailable"):
        await _service(FakeStore(), pending).pending(TENANT, "alice")


async def test_the_pending_key_is_the_ports_at_the_services_time():
    assert await _service(FakeStore(), Pending()).pending(TENANT, "alice") == PendingKey(
        bytes(32), NOW
    )
