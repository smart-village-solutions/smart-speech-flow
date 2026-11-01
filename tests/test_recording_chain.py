"""Conversation keys, wraps, encrypted objects and the signed chain (spec §8, §11.1)."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.chain import (
    GENESIS,
    ChainObject,
    chain_is_intact,
    entry_is_authentic,
    object_types,
    objects_json,
    seal_entry,
)
from services.api_gateway.recording.conversation_keys import (
    Recipient,
    new_conversation_key,
    seal_object,
    wrap_key,
)
from services.api_gateway.recording.crypto import aead, ecies, tags
from services.api_gateway.recording.crypto.signatures import verify_fields, wrap_fields
from services.api_gateway.recording.secrets import gateway_key_id
from tests import recording_crypto_reference as ref

TENANT = "tenant-a"
CONVERSATION = "0b3c1d4e-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
GATEWAY = ref.private_key(7)
GATEWAY_PUBLIC = ref.public_point(7)
GATEWAY_ID = gateway_key_id(GATEWAY_PUBLIC)
EMPLOYEE = Recipient("user", "alice", ref.public_point(21), b"\x21" * 32)


def _wrap(key, recipient=EMPLOYEE):
    return wrap_key(
        key,
        recipient,
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        signing_key=GATEWAY,
        signer_key_id=GATEWAY_ID,
    )


def test_a_conversation_key_is_32_random_bytes_with_its_own_id():
    first, second = new_conversation_key(1), new_conversation_key(1)

    assert len(first.secret) == 32
    assert first.secret != second.secret
    assert first.key_id != second.key_id
    assert first.secret.hex() not in repr(first)


def test_a_wrap_opens_for_its_recipient_in_its_own_context():
    key = new_conversation_key(1)
    wrap = _wrap(key)

    sealed = ecies.Sealed.from_json(wrap.blob, expected_type=tags.CK_WRAP)
    context = ecies.ck_wrap_context(TENANT, CONVERSATION, key.key_id, "user", "alice")
    assert ecies.open_with_private_key(sealed, ref.private_key(21), context) == key.secret


def test_a_wrap_moved_to_another_conversation_does_not_open():
    key = new_conversation_key(1)
    sealed = ecies.Sealed.from_json(_wrap(key).blob, expected_type=tags.CK_WRAP)
    elsewhere = ecies.ck_wrap_context(TENANT, "another", key.key_id, "user", "alice")

    with pytest.raises(ecies.SealedPayloadError):
        ecies.open_with_private_key(sealed, ref.private_key(21), elsewhere)


def test_a_wrap_is_signed_by_the_gateway_over_the_recipients_fingerprint():
    key = new_conversation_key(1)
    wrap = _wrap(key)
    sealed = ecies.Sealed.from_json(wrap.blob, expected_type=tags.CK_WRAP)

    def signed(fingerprint: bytes) -> tuple:
        return wrap_fields(
            TENANT, CONVERSATION, key.key_id, sealed.ephemeral, "user", "alice", fingerprint
        )

    assert wrap.creator_ref == GATEWAY_ID
    assert verify_fields(
        GATEWAY_PUBLIC, wrap.creator_signature, tags.WRAP_SIG, *signed(b"\x21" * 32)
    )
    assert not verify_fields(
        GATEWAY_PUBLIC, wrap.creator_signature, tags.WRAP_SIG, *signed(b"\x22" * 32)
    )


def test_an_object_opens_only_where_it_was_sealed():
    key = new_conversation_key(1)
    sealed = seal_object(
        key,
        b"hello",
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        entry_id="e1",
        object_type="record.json",
    )

    assert (
        aead.open_(
            key.secret,
            sealed,
            aead.object_aad(TENANT, CONVERSATION, "e1", "record.json", key.key_id),
        )
        == b"hello"
    )
    with pytest.raises(aead.EnvelopeError):
        aead.open_(
            key.secret,
            sealed,
            aead.object_aad(TENANT, CONVERSATION, "e1", "consent.json", key.key_id),
        )


OBJECTS = (
    ChainObject("record.json", "c/e/record.json", 120, "aa" * 32),
    ChainObject("original.wav", "c/e/original.wav", 64000, "bb" * 32),
)


def test_objects_are_canonical_whatever_order_they_come_in():
    assert objects_json(OBJECTS) == objects_json(tuple(reversed(OBJECTS)))
    assert [item["type"] for item in json.loads(objects_json(OBJECTS))] == [
        "original.wav",
        "record.json",
    ]
    assert object_types(objects_json(OBJECTS)) == {"original.wav", "record.json"}


def _chain(length: int):
    entries, previous = [], GENESIS
    for seq in range(1, length + 1):
        entry = seal_entry(
            tenant_id=TENANT,
            conversation_id=CONVERSATION,
            seq=seq,
            entry_id=f"entry-{seq}",
            kind="message",
            window_id="window-1",
            key_id="key-1",
            objects=OBJECTS,
            prev_hash=previous,
            created_at=NOW,
            signing_key=GATEWAY,
            signer_key_id=GATEWAY_ID,
        )
        entries.append(entry)
        previous = entry.hash
    return entries


def test_an_untouched_chain_is_intact():
    assert chain_is_intact(_chain(3), {GATEWAY_ID: GATEWAY_PUBLIC})


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "failed"},
        {"window_id": "window-2"},
        {"key_id": "key-2"},
        {"objects": objects_json(OBJECTS[:1])},
        {"tenant_id": "tenant-b"},
    ],
)
def test_altering_any_signed_field_of_an_entry_is_detected(change):
    entries = _chain(3)
    entries[1] = dataclasses.replace(entries[1], **change)

    assert not entry_is_authentic(entries[1], GATEWAY_PUBLIC)
    assert not chain_is_intact(entries, {GATEWAY_ID: GATEWAY_PUBLIC})


def test_removing_an_entry_is_detected():
    entries = _chain(3)
    del entries[1]

    assert not chain_is_intact(entries, {GATEWAY_ID: GATEWAY_PUBLIC})


def test_reordering_entries_is_detected():
    entries = _chain(3)
    entries[1], entries[2] = entries[2], entries[1]

    assert not chain_is_intact(entries, {GATEWAY_ID: GATEWAY_PUBLIC})


def test_an_entry_signed_by_an_unknown_key_is_rejected():
    assert not chain_is_intact(_chain(2), {"gk-other": GATEWAY_PUBLIC})


def test_a_forged_entry_with_a_recomputed_hash_still_fails_its_signature():
    entries = _chain(2)
    forger = ref.private_key(8)
    forged = seal_entry(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        seq=2,
        entry_id="entry-2",
        kind="failed",
        window_id="window-1",
        key_id="key-1",
        objects=OBJECTS,
        prev_hash=entries[0].hash,
        created_at=NOW,
        signing_key=forger,
        signer_key_id=GATEWAY_ID,
    )

    assert not chain_is_intact([entries[0], forged], {GATEWAY_ID: GATEWAY_PUBLIC})


def test_an_entry_outside_a_window_signs_an_empty_window():
    entry = seal_entry(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        seq=1,
        entry_id="entry-1",
        kind="playback",
        window_id=None,
        key_id="key-1",
        objects=OBJECTS[:1],
        prev_hash=GENESIS,
        created_at=NOW,
        signing_key=GATEWAY,
        signer_key_id=GATEWAY_ID,
    )

    assert entry_is_authentic(entry, GATEWAY_PUBLIC)
    assert not entry_is_authentic(dataclasses.replace(entry, window_id="w"), GATEWAY_PUBLIC)


def test_a_signed_entry_that_does_not_link_to_its_predecessor_is_detected():
    entries = _chain(3)
    forked = seal_entry(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        seq=2,
        entry_id="entry-2",
        kind="message",
        window_id="window-1",
        key_id="key-1",
        objects=OBJECTS,
        prev_hash=b"\x01" * 32,
        created_at=NOW,
        signing_key=GATEWAY,
        signer_key_id=GATEWAY_ID,
    )

    assert entry_is_authentic(forked, GATEWAY_PUBLIC)
    assert not chain_is_intact([entries[0], forked, entries[2]], {GATEWAY_ID: GATEWAY_PUBLIC})
