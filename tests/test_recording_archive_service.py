"""What a recorded conversation leaves in the archive (spec §5.3, §6, §7, §8.1, §11).

Driven through RecordingSessions, as the routes and the message path drive it,
over an in-memory repository, real spools and the filesystem store. Objects
are opened the way #616 will open them: through a wrap, with a private key.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording import session_service
from services.api_gateway.recording.archive_service import (
    ChainStamper,
    ConversationArchive,
    MessageArtefacts,
)
from services.api_gateway.recording.chain import ChainEntry, chain_is_intact
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.signatures import verify_fields, wrap_fields
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.session_service import RecordingUnavailableError
from services.api_gateway.recording.session_state import Phase, Reason
from services.api_gateway.recording.storage.spool import SpoolFullError
from services.api_gateway.recording.timestamps import Timestamp, TimestampUnavailableError
from tests.recording_archive_fakes import (
    EMPLOYEE_SCALAR,
    RECOVERY_SCALAR,
    conversation_key,
    decoded_objects,
    open_object,
    say_yes,
)
from tests.test_recording_session_service import ADMIN, GUEST, KEY, Harness

RESULT = {
    "error": False,
    "asr_text": "Guten Tag",
    "translation_text": "Good day",
    "raw_translation_text": "Good day",
    "audio_bytes": b"RIFF-translated",
    "debug": {"steps": []},
}


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


def _artefacts(h, message_id="m1", *, result=RESULT, audio=b"RIFF-original"):
    return MessageArtefacts(
        message_id=message_id,
        sender=GUEST,
        source_lang="de",
        target_lang="en",
        source_text="Guten Tag",
        result=result,
        original_audio=audio,
        accepted_at=h.clocks.now,
    )


async def _send(h, message_id="m1", **options):
    accepted = await h.service.accept(KEY)
    return await h.service.archive(KEY, accepted, _artefacts(h, message_id, **options))


def _chain(h) -> list[ChainEntry]:
    [conversation_id] = h.rig.repository.entries
    return h.rig.repository.chain(conversation_id)


def _conversation_key(h, entry: ChainEntry, *, scalar=RECOVERY_SCALAR) -> bytes:
    return conversation_key(h.rig, entry, scalar=scalar)


async def _object(h, entry: ChainEntry, object_type: str, *, scalar=RECOVERY_SCALAR) -> bytes:
    return await open_object(h.rig, entry, object_type, scalar=scalar)


def _gateway_keys(h) -> dict[str, bytes]:
    return {h.rig.secrets.signing_key_id: h.rig.secrets.signing_public_key}


async def test_a_yes_opens_the_conversation_with_a_signed_consent_entry(h):
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    state = await say_yes(h.service, KEY, "r1")

    [consent] = _chain(h)
    assert state.conversation_id == consent.conversation_id
    assert (consent.seq, consent.kind, consent.window_id) == (1, "consent", state.window_id)
    assert chain_is_intact([consent], _gateway_keys(h))
    record = json.loads(await _object(h, consent, "consent.json"))
    assert (record["request_id"], record["requested_by"], record["answer"]) == (
        "r1",
        "emp-sub",
        "yes",
    )
    assert record["legal_basis"] == "consent"
    assert [(e.actor_sub, e.event_type) for e in h.rig.repository.audit] == [
        ("guest", "recording.arming")
    ]
    # Audited once, with the consent entry, not again by the transition.
    assert "recording.arming" not in [e.event_type for e in h.audit]


async def test_the_conversation_key_is_wrapped_for_recovery_and_the_enrolled_employee(h):
    await h.on()
    [consent] = _chain(h)
    wraps = h.rig.repository.keys[consent.key_id].wraps

    assert {(w.recipient_kind, w.recipient_ref) for w in wraps} == {
        ("recovery", "5d1f3a2b-0000-4000-8000-00000000000a"),
        ("user", "emp-sub"),
    }
    assert _conversation_key(h, consent) == _conversation_key(h, consent, scalar=EMPLOYEE_SCALAR)
    for wrap in wraps:
        sealed = ecies.Sealed.from_json(wrap.blob, expected_type=tags.CK_WRAP)
        fingerprint = b"\x31" * 32 if wrap.recipient_kind == "recovery" else b"\x21" * 32
        signed = wrap_fields(
            KEY.tenant_id,
            consent.conversation_id,
            consent.key_id,
            sealed.ephemeral,
            wrap.recipient_kind,
            wrap.recipient_ref,
            fingerprint,
        )
        assert verify_fields(
            h.rig.secrets.signing_public_key, wrap.creator_signature, tags.WRAP_SIG, *signed
        )


async def test_an_employee_without_keys_still_records_for_recovery_only(h):
    h.rig.employee_enrolled = False
    await h.on()

    [consent] = _chain(h)
    assert [w.recipient_kind for w in h.rig.repository.keys[consent.key_id].wraps] == ["recovery"]


@pytest.mark.parametrize("fault", ["database", "recovery_key", "spool_full"])
async def test_a_yes_the_archive_cannot_record_is_refused_and_changes_nothing(h, fault):
    if fault == "database":
        h.rig.repository.down = True
    elif fault == "recovery_key":
        h.rig.recovery_present = False
    else:
        h.rig.spools.spool(KEY.tenant_id)._capacity = 0
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    frames = len(h.announcer.frames)

    with pytest.raises(RecordingUnavailableError) as error:
        await say_yes(h.service, KEY, "r1")

    assert error.value.code == "ARCHIVE_WRITE_FAILED"
    assert (await h.service.state(KEY)).phase is Phase.ASKING
    assert h.rig.repository.entries == {} and h.rig.repository.audit == []
    # No state changed; only the employee hears why the yes failed.
    assert [f["type"] for f, _ in h.announcer.frames[frames:]] == ["recording_error"]


async def test_a_message_while_on_is_archived_with_both_audios_and_its_record(h):
    await h.on()

    entry_id = await _send(h)

    message = _chain(h)[-1]
    assert (message.entry_id, message.kind, message.seq) == (entry_id, "message", 2)
    assert {o["type"] for o in decoded_objects(message)} == {
        "original.wav",
        "translated.wav",
        "record.json",
    }
    assert await _object(h, message, "original.wav") == b"RIFF-original"
    assert await _object(h, message, "translated.wav") == b"RIFF-translated"
    record = json.loads(await _object(h, message, "record.json"))
    assert (record["message_id"], record["final_text"], record["sender"]) == (
        "m1",
        "Good day",
        "customer",
    )
    assert chain_is_intact(_chain(h), _gateway_keys(h))


async def test_a_typed_message_has_no_original_audio(h):
    await h.on()

    await _send(h, audio=None)

    assert {o["type"] for o in decoded_objects(_chain(h)[-1])} == {"translated.wav", "record.json"}


async def test_a_failed_pipeline_archives_the_original_and_the_error_and_marks_the_gap(h):
    await h.on()
    failed = {"error": True, "error_msg": "TTS", "debug": {"failed_stage": "tts", "steps": []}}

    await _send(h, result=failed)

    entry = _chain(h)[-1]
    assert entry.kind == "failed"
    assert {o["type"] for o in decoded_objects(entry)} == {"original.wav", "record.json"}
    assert json.loads(await _object(h, entry, "record.json"))["error"]["stage"] == "tts"
    assert entry.conversation_id in h.rig.repository.incomplete


async def _stop(h):
    await h.service.stop(KEY, role=ADMIN, actor="emp-sub")


async def _pause_and_resume(h):
    h.announcer.guest_connected = False
    h.service.released(KEY, GUEST)
    await h.service.tick()
    h.announcer.guest_connected = True
    await h.ack_both()


async def _lose_ack(h):
    h.clocks.advance(11)
    await h.service.pause(KEY, Reason.UNACKNOWLEDGED)


async def _lose_liveness(h):
    h.clocks.advance(13)


async def _policy_fails(h):
    h.policy_fails = True


@pytest.mark.parametrize("disturbance", [_stop, _pause_and_resume, _lose_ack, _lose_liveness])
async def test_a_message_whose_processing_spans_a_disturbance_is_not_stored(h, disturbance):
    await h.on()
    accepted = await h.service.accept(KEY)

    await disturbance(h)
    stored = await h.service.archive(KEY, accepted, _artefacts(h))

    assert stored is None
    assert [entry.kind for entry in _chain(h)] == ["consent"]


async def test_a_failed_policy_read_at_acceptance_pauses_and_stores_nothing(h):
    await h.on()
    h.policy_fails = True

    assert await _send(h) is None

    state = await h.service.state(KEY)
    assert (state.phase, state.reason) == (Phase.PAUSED, Reason.POLICY)
    assert [entry.kind for entry in _chain(h)] == ["consent"]


async def test_a_disabled_policy_at_acceptance_pauses_too(h):
    await h.on()
    h.policy = h.policy.model_copy(update={"enabled": False})

    assert await _send(h) is None
    assert (await h.service.state(KEY)).reason is Reason.POLICY


async def test_no_message_is_stored_while_recording_is_off(h):
    assert await _send(h) is None
    assert h.rig.repository.entries == {}


async def test_concurrent_messages_get_distinct_consecutive_entries(h):
    await h.on()

    accepted = [await h.service.accept(KEY) for _ in range(5)]
    await asyncio.gather(
        *(
            h.service.archive(KEY, snapshot, _artefacts(h, f"m{index}"))
            for index, snapshot in enumerate(accepted)
        )
    )

    chain = _chain(h)
    assert [entry.seq for entry in chain] == [1, 2, 3, 4, 5, 6]
    assert chain_is_intact(chain, _gateway_keys(h))


async def test_concurrent_messages_and_a_stop_store_only_what_was_decided_before_it(h):
    await h.on()
    accepted = await h.service.accept(KEY)

    results = await asyncio.gather(
        h.service.archive(KEY, accepted, _artefacts(h, "before")),
        h.service.stop(KEY, role=GUEST, actor="guest"),
        h.service.archive(KEY, accepted, _artefacts(h, "after")),
    )

    assert results[0] is not None and results[2] is None
    assert [entry.kind for entry in _chain(h)] == ["consent", "message"]


@pytest.mark.parametrize("fault", ["database", "spool_full"])
async def test_an_archive_fault_pauses_for_storage_and_the_message_goes_unstored(h, fault):
    await h.on()
    if fault == "database":
        h.rig.repository.down = True
    else:
        h.rig.spools.spool(KEY.tenant_id)._capacity = 0

    assert await _send(h) is None

    state = await h.service.state(KEY)
    assert (state.phase, state.reason) == (Phase.PAUSED, Reason.STORAGE)
    assert "paused" in h.announcer.states()


async def test_recording_resumes_after_a_storage_pause_once_the_archive_recovers(h):
    await h.on()
    h.rig.repository.down = True
    await _send(h)
    h.rig.repository.down = False

    await h.ack_both()
    await h.ack_both()

    assert (await h.service.state(KEY)).phase is Phase.ON
    assert await _send(h, "m2") is not None


async def test_playback_of_an_archived_message_is_its_own_entry(h):
    await h.on()
    entry_id = await _send(h)

    await h.service.playback(KEY, ADMIN, "m1", "completed")

    playback = _chain(h)[-1]
    assert playback.kind == "playback"
    record = json.loads(await _object(h, playback, "playback.json"))
    assert (record["message_entry_id"], record["event"], record["reported_by"]) == (
        entry_id,
        "completed",
        "admin",
    )


async def test_playback_of_an_unarchived_message_or_while_not_on_is_not_archived(h):
    await h.on()
    await _send(h)

    await h.service.playback(KEY, ADMIN, "never-archived", "started")
    await _stop(h)
    await h.service.playback(KEY, ADMIN, "m1", "started")

    assert [entry.kind for entry in _chain(h)] == ["consent", "message"]


async def test_pauses_and_the_close_of_a_window_are_recorded_with_a_stamp_request(h):
    await h.on()
    window_id = (await h.service.state(KEY)).window_id
    await _pause_and_resume(h)
    await h.ack_both()

    await _stop(h)

    window = h.rig.repository.windows[window_id]
    assert [p["reason"] for p in window["pauses"]] == ["liveness"]
    assert window["pauses"][0]["resumed_at"] is not None
    assert window["closed"] == "stopped_by_employee"
    assert list(h.rig.repository.stamps) == [(_chain(h)[0].conversation_id, 1)]


async def test_a_resume_reuses_the_conversation_and_its_key(h):
    await h.on()
    await _stop(h)
    await h.service.request(KEY, request_id="r2", requested_by="emp-sub")
    await say_yes(h.service, KEY, "r2")

    first, second = _chain(h)
    assert (second.kind, second.seq, second.key_id) == ("consent", 2, first.key_id)
    assert first.window_id != second.window_id
    assert json.loads(await _object(h, second, "consent.json"))["kind"] == "resume"


async def test_session_end_ends_the_conversation_and_drops_its_key(h):
    await h.on()
    conversation_id = _chain(h)[0].conversation_id

    await h.service.session_ended(KEY)

    assert conversation_id in h.rig.repository.ended
    assert h.rig.archive._keys == {}
    assert list(h.rig.repository.stamps) == [(conversation_id, 1)]


async def test_after_a_restart_the_chain_continues_under_a_new_key_epoch(h):
    await h.on()
    await _send(h)
    # A new gateway process: same database and state, empty memory.
    h.rig.archive = ConversationArchive(
        repository=h.rig.repository,
        spools=h.rig.spools,
        secrets=h.rig.secrets,
        recovery_key=h.rig.archive._recovery_key,
        user_key=h.rig.archive._user_key,
        session_ref=lambda session_id: "ref",
        clock=lambda: h.clocks.now,
    )
    h.service._archive = h.rig.archive

    await _send(h, "m2")

    first, second, third = _chain(h)
    assert third.seq == 3 and third.prev_hash == second.hash
    assert third.key_id != second.key_id
    assert h.rig.repository.keys[third.key_id].epoch == 2
    assert chain_is_intact(_chain(h), _gateway_keys(h))
    assert await _object(h, third, "original.wav") == b"RIFF-original"


class Authority:
    def __init__(self, fail=False):
        self.fail, self.digests = fail, []

    async def stamp(self, url, digest):
        self.digests.append((url, digest))
        if self.fail:
            raise TimestampUnavailableError("unreachable")
        return Timestamp(b"token-" + digest[:4], datetime(2026, 10, 27, tzinfo=timezone.utc))


async def test_a_closed_window_is_stamped_once_its_entries_are_stored(h):
    await h.on()
    await _send(h)
    await _stop(h)
    authority = Authority()
    stamper = ChainStamper(
        h.rig.repository, authority, lambda: [KEY.tenant_id], lambda: h.clocks.now
    )

    await stamper.run_once()
    assert authority.digests == []  # the objects are still in the spool

    assert await h.rig.spools.flush()
    await stamper.run_once()

    head = _chain(h)[-1]
    assert authority.digests == [("https://tsa.example.org/tsr", head.hash)]
    [stamp] = h.rig.repository.stamps.values()
    assert stamp["token"] == b"token-" + head.hash[:4]


async def test_an_unreachable_authority_defers_the_stamp_without_touching_recording(h):
    await h.on()
    await _stop(h)
    assert await h.rig.spools.flush()
    stamper = ChainStamper(
        h.rig.repository, Authority(fail=True), lambda: [KEY.tenant_id], lambda: h.clocks.now
    )

    await stamper.run_once()
    await stamper.run_once()

    [stamp] = h.rig.repository.stamps.values()
    assert stamp["token"] is None and stamp["attempts"] == 1
    assert stamp["next"] > h.clocks.now


async def test_no_object_names_a_guest_or_the_plaintext(h):
    await h.on()
    await _send(h)
    assert await h.rig.spools.flush()

    for path in (h.rig.store._root).rglob("*"):
        if path.is_file():
            assert b"Guten Tag" not in path.read_bytes()
            assert b"RIFF-original" not in path.read_bytes()


def test_artefacts_of_a_failed_result_carry_no_translated_audio(h):
    failed = dataclasses.replace(_artefacts(h), result={"error": True, "audio_bytes": b"x"})
    assert failed.translated_audio is None


# Review round (2026-10-27): partial failures, timeouts, consent "no", playback limits.


async def _asking(h, request_id="r1"):
    await h.service.request(KEY, request_id=request_id, requested_by="emp-sub")


async def test_a_yes_committed_before_its_spool_write_failed_still_stands(h, monkeypatch):
    def refuse(*_args):
        raise SpoolFullError()

    monkeypatch.setattr(h.rig.spools.spool(KEY.tenant_id), "submit", refuse)
    await _asking(h)

    state = await say_yes(h.service, KEY, "r1")

    assert state.phase is Phase.ARMING and state.conversation_id is not None
    assert list(h.rig.repository.conversations) == [state.conversation_id]
    assert state.conversation_id in h.rig.repository.incomplete


async def test_a_yes_whose_state_was_not_saved_reuses_its_conversation_on_retry(h, monkeypatch):
    real_save = h.store.save
    failed = []

    async def save_failing_once(key, state):
        if state.phase is Phase.ARMING and not failed:
            failed.append(state)
            raise ConnectionError("redis down")
        await real_save(key, state)

    monkeypatch.setattr(h.store, "save", save_failing_once)
    await _asking(h)
    with pytest.raises(ConnectionError):
        await say_yes(h.service, KEY, "r1")

    state = await say_yes(h.service, KEY, "r1")

    assert list(h.rig.repository.conversations) == [state.conversation_id]
    assert [entry.kind for entry in _chain(h)] == ["consent", "consent"]
    assert chain_is_intact(_chain(h), _gateway_keys(h))
    await h.service.session_ended(KEY)
    assert h.rig.archive._keys == {}
    assert all(window["closed"] for window in h.rig.repository.windows.values())


async def test_a_yes_whose_commit_landed_but_failed_is_retried_into_the_same_conversation(h):
    await _asking(h)
    h.rig.repository.lands_then_fails = True
    with pytest.raises(RecordingUnavailableError):
        await say_yes(h.service, KEY, "r1")

    state = await say_yes(h.service, KEY, "r1")

    assert list(h.rig.repository.conversations) == [state.conversation_id]
    assert [entry.seq for entry in _chain(h)] == [1, 2]
    assert chain_is_intact(_chain(h), _gateway_keys(h))


async def test_an_ambiguous_commit_does_not_wedge_the_conversation(h):
    await h.on()
    h.rig.repository.lands_then_fails = True
    assert await _send(h) is None
    await h.ack_both()
    await h.ack_both()

    assert await _send(h, "m2") is not None

    chain = _chain(h)
    assert [entry.seq for entry in chain] == [1, 2, 3]
    assert chain_is_intact(chain, _gateway_keys(h))
    assert chain[2].key_id != chain[1].key_id  # memory was dropped: a new epoch


async def test_a_hung_database_cannot_hold_a_message_for_long(h, monkeypatch):
    monkeypatch.setattr(session_service, "ARCHIVE_SECONDS", 0.2)
    await h.on()
    hang = asyncio.Event()

    async def hung(entry, key):
        await hang.wait()

    monkeypatch.setattr(h.rig.repository, "append_entry", hung)

    assert await asyncio.wait_for(_send(h), 2) is None
    state = await h.service.state(KEY)
    assert (state.phase, state.reason) == (Phase.PAUSED, Reason.STORAGE)


async def test_a_declined_resume_is_its_own_consent_entry(h):
    await h.on()
    await _stop(h)
    await _asking(h, "r2")

    await h.service.answer(KEY, request_id="r2", consent=False)

    declined = _chain(h)[-1]
    assert (declined.kind, declined.window_id) == ("consent", None)
    record = json.loads(await _object(h, declined, "consent.json"))
    assert (record["answer"], record["kind"], record["request_id"]) == ("no", "resume", "r2")


async def test_a_no_before_any_yes_leaves_no_entry(h):
    await _asking(h)

    await h.service.answer(KEY, request_id="r1", consent=False)

    assert h.rig.repository.entries == {}


async def test_a_tenant_without_an_archive_credential_cannot_record(h):
    h.rig.writer_ready = False

    with pytest.raises(RecordingUnavailableError) as error:
        await h.service.request(KEY, request_id="r1", requested_by="emp-sub")

    assert error.value.code == "ARCHIVE_UNAVAILABLE"


async def test_playback_counts_once_per_event_and_only_from_the_receiving_screen(h):
    await h.on()
    await _send(h)  # sent by the guest

    await h.service.playback(KEY, GUEST, "m1", "completed")
    await h.service.playback(KEY, ADMIN, "m1", "completed")
    await h.service.playback(KEY, ADMIN, "m1", "completed")

    assert [entry.kind for entry in _chain(h)] == ["consent", "message", "playback"]
    record = json.loads(await _object(h, _chain(h)[-1], "playback.json"))
    assert record["reported_by"] == "admin"


async def test_an_end_that_could_not_be_written_is_written_later(h):
    await h.on()
    conversation_id = _chain(h)[0].conversation_id
    h.rig.repository.down = True
    await h.service.session_ended(KEY)
    h.rig.repository.down = False

    await h.rig.archive.retry_pending_ends()

    assert conversation_id in h.rig.repository.ended


async def test_the_employee_hears_when_a_yes_could_not_be_recorded(h):
    await _asking(h)
    h.rig.repository.down = True

    with pytest.raises(RecordingUnavailableError):
        await say_yes(h.service, KEY, "r1")

    errors = [(f, role) for f, role in h.announcer.frames if f["type"] == "recording_error"]
    assert [(f["code"], role) for f, role in errors] == [("ARCHIVE_WRITE_FAILED", ADMIN)]


async def test_the_policy_is_read_for_the_state_the_message_is_accepted_in(h, monkeypatch):
    await h.on()
    on = await h.service.state(KEY)
    paused = dataclasses.replace(on, phase=Phase.PAUSED)
    real_load = h.store.load
    calls = []

    async def load(key):
        calls.append(key)
        return paused if len(calls) == 1 else await real_load(key)

    monkeypatch.setattr(h.store, "load", load)
    h.policy_fails = True

    assert not (await h.service.accept(KEY)).holds()


class FaultyAuthority:
    async def stamp(self, url, digest):
        raise ValueError("microsecond must be in 0..999999")


async def test_any_stamping_fault_defers_that_stamp_and_the_pass_goes_on(h, monkeypatch):
    await h.on()
    await _stop(h)
    assert await h.rig.spools.flush()
    real_pending = h.rig.repository.pending_stamps

    async def pending(tenant_id, now):
        if tenant_id == "tenant-broken":
            raise RecordingStorageUnavailable("down")
        return await real_pending(tenant_id, now)

    monkeypatch.setattr(h.rig.repository, "pending_stamps", pending)
    stamper = ChainStamper(
        h.rig.repository,
        FaultyAuthority(),
        lambda: ["tenant-broken", KEY.tenant_id],
        lambda: h.clocks.now,
    )

    await stamper.run_once()

    [stamp] = h.rig.repository.stamps.values()
    assert stamp["attempts"] == 1 and stamp["next"] > h.clocks.now
