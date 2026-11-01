"""Consent capture through RecordingSessions: the served text, name, signature, ID check (§6)."""

from __future__ import annotations

import base64
import json

import pytest

from services.api_gateway.recording.consent_evidence import ConsentEvidenceError, GuestAnswer
from services.api_gateway.recording.consent_text import consent_text
from services.api_gateway.recording.session_state import (
    Phase,
    RecordingConflictError,
)
from services.api_gateway.studio_v2 import RecordingPolicy, RecordingTexts
from tests.recording_archive_fakes import GUEST_NAME, open_object, say_yes
from tests.test_recording_session_service import ADMIN, GUEST, KEY, POLICY_FIELDS, Harness

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


def _policy(h: Harness, **fields) -> None:
    h.policy = RecordingPolicy.model_validate(POLICY_FIELDS | fields)


async def _consent_record(h: Harness) -> dict:
    [conversation_id] = h.rig.repository.entries
    entry = h.rig.repository.chain(conversation_id)[-1]
    assert entry.kind == "consent"
    return json.loads(await open_object(h.rig, entry, "consent.json"))


async def _ack_both(h: Harness) -> None:
    await h.ack_both()
    await h.ack_both()


async def test_the_open_question_is_served_in_the_guests_language(h) -> None:
    _policy(h, signature="required")
    await h.service.request(KEY, request_id="r1", requested_by="emp", proposed_name="Amira Haddad")

    served = await h.service.consent(KEY, "ar")

    assert (served.request_id, served.kind, served.signature) == ("r1", "first", "required")
    assert served.proposed_name == "Amira Haddad"
    assert served.text == consent_text(h.policy, "ar", "first")


async def test_without_an_open_question_there_is_no_text(h) -> None:
    with pytest.raises(RecordingConflictError):
        await h.service.consent(KEY, "en")
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    await say_yes(h.service, KEY, "r1")
    with pytest.raises(RecordingConflictError):
        await h.service.consent(KEY, "en")  # answered: the question is closed


async def test_a_resume_asks_for_the_text_alone(h) -> None:
    await h.on()
    await h.service.stop(KEY, role=GUEST, actor="guest")
    _policy(h, signature="required")
    await h.service.request(KEY, request_id="r2", requested_by="emp", proposed_name="X")

    served = await h.service.consent(KEY, "en")

    assert (served.kind, served.signature, served.proposed_name) == ("resume", "off", None)
    assert (await h.service.state(KEY)).proposed_name is None


async def test_the_first_yes_archives_its_evidence(h) -> None:
    _policy(h, signature="optional", idCheck="optional")
    await h.service.request(
        KEY, request_id="r1", requested_by="emp", proposed_name=GUEST_NAME, id_checked=True
    )
    asked = await h.service.state(KEY)

    state = await say_yes(h.service, KEY, "r1", language="ar", signature_png=PNG)

    record = await _consent_record(h)
    assert record["text"] == consent_text(h.policy, "ar", "first").record()
    assert record["text_de"]["language"] == "de"
    assert record["guest"] == {"name": GUEST_NAME, "entered_by": "employee"}
    assert record["signature"]["png"] == base64.b64encode(PNG).decode()
    assert record["id_check"] == {
        "policy": "optional",
        "checked": True,
        "at": asked.since.isoformat(),
    }
    assert (record["answer"], record["requested_by"]) == ("yes", "emp")
    # The name lived in the state only while the guest was asked.
    assert (state.proposed_name, state.id_checked_at) == (None, None)


async def test_a_yes_with_another_texts_hash_is_refused_and_the_question_stays(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    tampered = GuestAnswer("en", "0" * 64, name=GUEST_NAME)

    with pytest.raises(ConsentEvidenceError) as refused:
        await h.service.answer(KEY, request_id="r1", consent=True, reply=tampered)

    assert refused.value.code == "CONSENT_TEXT_MISMATCH"
    assert (await h.service.state(KEY)).phase is Phase.ASKING
    assert h.rig.repository.entries == {}


async def test_a_text_changed_after_it_was_served_refuses_the_yes(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    served = await h.service.consent(KEY, "en")
    h.policy = h.policy.model_copy(
        update={
            "texts": (
                RecordingTexts(
                    locale="en", consent_html="<p>New</p>", resume_prompt_html="<p>R</p>"
                ),
            )
        }
    )
    reply = GuestAnswer("en", served.text.sha256, name=GUEST_NAME)

    with pytest.raises(ConsentEvidenceError) as refused:
        await h.service.answer(KEY, request_id="r1", consent=True, reply=reply)

    assert refused.value.code == "CONSENT_TEXT_MISMATCH"


async def test_a_no_needs_no_evidence(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")

    state = await h.service.answer(KEY, request_id="r1", consent=False)

    assert state.phase is Phase.OFF


async def test_a_required_id_check_refuses_a_first_request_without_it(h) -> None:
    _policy(h, idCheck="required")

    with pytest.raises(ConsentEvidenceError) as refused:
        await h.service.request(KEY, request_id="r1", requested_by="emp")

    assert (refused.value.code, refused.value.status) == ("ID_CHECK_REQUIRED", 422)
    assert (await h.service.state(KEY)).phase is Phase.OFF
    checked = await h.service.request(KEY, request_id="r2", requested_by="emp", id_checked=True)
    assert checked.id_checked_at == checked.since


async def test_a_resume_needs_no_id_check(h) -> None:
    _policy(h, idCheck="required")
    await h.service.request(KEY, request_id="r1", requested_by="emp", id_checked=True)
    await say_yes(h.service, KEY, "r1")
    await _ack_both(h)
    await h.service.stop(KEY, role=ADMIN, actor="emp")

    resumed = await h.service.request(KEY, request_id="r2", requested_by="emp", id_checked=True)

    assert (resumed.phase, resumed.request_kind, resumed.id_checked_at) == (
        Phase.ASKING,
        "resume",
        None,
    )


async def test_an_id_check_the_policy_does_not_offer_is_not_recorded(h) -> None:
    _policy(h, idCheck="off")

    state = await h.service.request(KEY, request_id="r1", requested_by="emp", id_checked=True)

    assert state.id_checked_at is None


async def test_a_declined_resume_cites_the_text_its_screen_was_served(h) -> None:
    await h.on()
    await h.service.stop(KEY, role=GUEST, actor="guest")
    await h.service.request(KEY, request_id="r2", requested_by="emp")
    served = await h.service.consent(KEY, "uk")

    await h.service.answer(KEY, request_id="r2", consent=False)

    record = await _consent_record(h)
    assert (record["answer"], record["text"]) == ("no", served.text.record())


async def test_a_resume_declined_unseen_cites_no_text(h) -> None:
    await h.on()
    await h.service.stop(KEY, role=GUEST, actor="guest")
    await h.service.request(KEY, request_id="r2", requested_by="emp")

    await h.service.stop(KEY, role=GUEST, actor="guest")

    record = await _consent_record(h)
    assert record["answer"] == "no"
    assert "text" not in record
