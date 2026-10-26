"""Key enrolment stores only a checked, doubly sealed blob (spec §8.3)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.keys import Enrolment, InvalidEnrolment, KeyEnrolmentService
from services.api_gateway.recording.repository import KeyAlreadyEnrolledError
from services.api_gateway.recording.secrets import ServerLayer
from tests import recording_crypto_reference as ref
from tests.recording_fakes import FakeRecordingRepository, sealed_blob, with_kdf

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
ENC, SIG = ref.public_point(11), ref.public_point(12)


@pytest.fixture
def repository():
    return FakeRecordingRepository()


@pytest.fixture
def service(repository):
    return KeyEnrolmentService(
        repository=repository, server_layer=ServerLayer(os.urandom(32)), clock=lambda: NOW
    )


async def test_enrolment_stores_the_blob_under_the_server_layer(service, repository):
    blob = sealed_blob()
    returned = await service.enrol("tenant-test", "alice", Enrolment(ENC, SIG, blob))
    assert returned == fingerprint("tenant-test", "alice", ENC, SIG)
    stored = repository.keys[("tenant-test", "alice")]
    assert blob.encode() not in stored.encrypted_private
    assert [event.event_type for event in repository.audit] == ["key_enrolled"]


async def test_own_key_returns_the_blob_and_audits_the_read(service, repository):
    blob = sealed_blob()
    await service.enrol("tenant-test", "alice", Enrolment(ENC, SIG, blob))
    key = await service.own_key("tenant-test", "alice")
    assert key is not None and key.blob == blob
    assert repository.audit[-1].event_type == "key_blob_read"


async def test_a_second_enrolment_is_refused(service):
    await service.enrol("tenant-test", "alice", Enrolment(ENC, SIG, sealed_blob()))
    with pytest.raises(KeyAlreadyEnrolledError):
        await service.enrol("tenant-test", "alice", Enrolment(ENC, SIG, sealed_blob()))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda blob: with_kdf(blob, m=1024),
        lambda blob: with_kdf(blob, t=1),
        lambda blob: with_kdf(blob, p=0),
        lambda blob: with_kdf(blob, alg="pbkdf2"),
        lambda blob: with_kdf(blob, salt="AAAA"),
        lambda blob: with_kdf(blob, m=True),
        lambda blob: json.dumps({**json.loads(blob), "sig": {"nonce": "AAAA", "ct": "AAAA"}}),
        lambda blob: "not json",
        lambda blob: blob + " " * 4096,
    ],
)
async def test_a_blob_below_the_floor_or_out_of_shape_is_refused(service, mutate):
    with pytest.raises(InvalidEnrolment):
        await service.enrol("tenant-test", "alice", Enrolment(ENC, SIG, mutate(sealed_blob())))


async def test_invalid_or_identical_public_keys_are_refused(service):
    with pytest.raises(InvalidEnrolment):
        await service.enrol(
            "tenant-test", "alice", Enrolment(ENC[:-1] + b"\x00", SIG, sealed_blob())
        )
    with pytest.raises(InvalidEnrolment):
        await service.enrol("tenant-test", "alice", Enrolment(ENC, ENC, sealed_blob()))
