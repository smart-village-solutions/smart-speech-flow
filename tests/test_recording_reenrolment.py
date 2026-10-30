"""Re-enrolment waits on its confirmation port, then swaps the key (spec §9.6)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.keys import Enrolment
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment import (
    ImmediateConfirmation,
    KeyReenrolment,
    ReenrolmentError,
)
from services.api_gateway.recording.reenrolment_repository import ReenrolmentImpact
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.secrets import ServerLayer
from tests import recording_crypto_reference as ref
from tests.recording_fakes import sealed_blob

TENANT = "tenant-a"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
ENROLMENT = Enrolment(ref.public_point(7), ref.public_point(8), sealed_blob())


class FakeStore:
    def __init__(
        self,
        answer: Refused | None = None,
        error: BaseException | None = None,
        checked: Refused | None = None,
    ):
        self.answer, self.error, self.checked = answer, error, checked
        self.swaps: list[tuple] = []

    async def check(self, tenant_id, sub, replaces_version, now):
        if self.error is not None:
            raise self.error
        return self.checked

    async def swap(self, record, replaces_version, now):
        if self.error is not None:
            raise self.error
        self.swaps.append((record, replaces_version, now))
        return self.answer

    async def impact(self, tenant_id, sub):
        if self.error is not None:
            raise self.error
        return ReenrolmentImpact(True, 2, 1)


class Pending:
    def __init__(self) -> None:
        self.asked: list[tuple] = []

    async def request(self, record, replaces_version):
        self.asked.append((record.tenant_id, record.user_sub, replaces_version, record.key_version))
        return False


def _service(store, confirmation=None):
    return KeyReenrolment(
        store=store,
        server_layer=ServerLayer(os.urandom(32)),
        confirmation=confirmation or ImmediateConfirmation(),
        clock=lambda: NOW,
    )


async def test_a_confirmed_re_enrolment_swaps_the_next_version_now():
    store = FakeStore()

    done = await _service(store).reenrol(TENANT, "alice", ENROLMENT, 1)

    [(record, replaces, at)] = store.swaps
    assert (record.key_version, replaces, at) == (2, 1, NOW)
    assert record.encrypted_private != ENROLMENT.blob.encode()
    expected = fingerprint(TENANT, "alice", ENROLMENT.enc_pub, ENROLMENT.sig_pub)
    assert (done.status, done.fingerprint) == ("active", expected)


async def test_a_pending_confirmation_answers_pending_and_swaps_nothing():
    store, pending = FakeStore(), Pending()

    done = await _service(store, pending).reenrol(TENANT, "alice", ENROLMENT, 3)

    assert done.status == "pending_confirmation"
    assert pending.asked == [(TENANT, "alice", 3, 4)] and store.swaps == []


async def test_a_refusal_is_known_before_any_confirmation_is_asked_for():
    pending = Pending()
    store = FakeStore(checked=Refused("key_changed"))
    with pytest.raises(ReenrolmentError, match="key_changed"):
        await _service(store, pending).reenrol(TENANT, "alice", ENROLMENT, 1)
    assert pending.asked == [] and store.swaps == []


async def test_an_invalid_body_is_refused_before_the_port_is_asked():
    pending = Pending()
    bad = Enrolment(ref.public_point(7), ref.public_point(7), sealed_blob())
    with pytest.raises(ReenrolmentError, match="invalid"):
        await _service(FakeStore(), pending).reenrol(TENANT, "alice", bad, 1)
    assert pending.asked == []


@pytest.mark.parametrize("code", ["key_not_enrolled", "key_changed", "ceremony_in_progress"])
async def test_each_refusal_of_the_swap_passes_through(code):
    with pytest.raises(ReenrolmentError, match=code):
        await _service(FakeStore(Refused(code))).reenrol(TENANT, "alice", ENROLMENT, 1)


async def test_a_storage_failure_is_unavailable():
    failing = FakeStore(error=RecordingStorageUnavailable("down"))
    with pytest.raises(ReenrolmentError, match="unavailable"):
        await _service(failing).reenrol(TENANT, "alice", ENROLMENT, 1)
    with pytest.raises(ReenrolmentError, match="unavailable"):
        await _service(failing).impact(TENANT, "alice")


async def test_the_impact_is_the_stores():
    assert await _service(FakeStore()).impact(TENANT, "carol") == ReenrolmentImpact(True, 2, 1)
