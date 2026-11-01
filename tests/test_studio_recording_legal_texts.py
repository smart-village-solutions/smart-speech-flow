"""Synthetic Studio legal wording across parsing, display and recording evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest

from services.api_gateway.content_responses import guest_content_response, staff_content_response
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_v2 import parse_runtime_configuration_v2
from tests.studio_v2_fixtures import KASSEL, load_fixture
from tests.test_recording_session_service import POLICY_FIELDS


def choice(name: str) -> dict[str, str]:
    return {
        "headline": name,
        "bodyHtml": f"<p>{name} body</p>",
        "acceptLabel": f"Accept {name}",
        "declineLabel": f"Decline {name}",
    }


def legal_block() -> dict:
    return {
        "sourceLocale": "de-DE",
        "version": "synthetic-draft-1",
        "localizations": [
            {
                "locale": "de-DE",
                "mode2Consent": choice("Documentation"),
                "mode3Consent": choice("Quality only"),
                "guestRecordingRelease": choice("Guest release"),
                "staffRecordingRelease": choice("Employee release"),
                "recordingStatus": {
                    "waiting": "Waiting",
                    "running": "Running",
                    "stopped": "Stopped",
                    "renewedReleaseRequired": "Release again",
                },
            }
        ],
    }


def runtime(legal: dict | None = None, *, tenant: str = "tenant-kassel", recording=True):
    body = load_fixture(KASSEL)
    body["tenant"]["id"] = tenant
    if legal is not None:
        body["legalTexts"] = legal
    if recording:
        body["recording"] = deepcopy(POLICY_FIELDS)
    return parse_runtime_configuration_v2(body, expected_tenant_id=tenant)


def test_legal_content_is_optional_and_never_enables_recording():
    assert runtime().content.legal_texts is None
    read = runtime(legal_block(), recording=False)
    assert read.policy.recording is None
    assert read.content.legal_texts.version == "synthetic-draft-1"


def test_legal_html_is_sanitized_and_uses_a_valid_source_locale():
    block = legal_block()
    block["localizations"][0]["guestRecordingRelease"][
        "bodyHtml"
    ] = '<p onclick="x()">Safe</p><script>private()</script>'
    legal = runtime(block).content.legal_texts
    assert legal.localizations[0].guest_recording_release.body_html == "<p>Safe</p>"
    block["sourceLocale"] = "fr"
    assert runtime(block).content.legal_texts is None
    block = legal_block()
    block["localizations"].append(deepcopy(block["localizations"][0]))
    assert runtime(block).content.legal_texts is None


def test_bad_legal_content_does_not_drop_policy_or_other_content():
    block = legal_block()
    block["localizations"][0]["mode2Consent"]["acceptLabel"] = ""
    read = runtime(block)
    assert read.content.legal_texts is None
    assert read.policy.recording.enabled is True
    assert read.content.staff is not None


def test_status_copy_is_tenant_scoped_and_independent_of_guest_coverage():
    cache = StudioContentCache()
    read = runtime(legal_block())
    kassel = cache.record(read)
    guest = guest_content_response(kassel, "xx").model_dump(by_alias=True)
    assert guest["provided"] is False
    assert guest["recordingStatus"] == {
        "locale": "de-DE",
        "waiting": "Waiting",
        "running": "Running",
        "stopped": "Stopped",
        "renewedReleaseRequired": "Release again",
    }
    assert (
        staff_content_response(kassel).model_dump(by_alias=True)["recordingStatus"]
        == guest["recordingStatus"]
    )
    other = cache.record(runtime(tenant="other-tenant"))
    assert guest_content_response(other, "xx").model_dump(by_alias=True)["recordingStatus"] is None


def test_documentation_and_release_are_distinct_and_repeated_for_renewal():
    from services.api_gateway.recording.consent_text import consent_text

    policy = runtime(legal_block()).policy.recording
    for kind in ("first", "resume"):
        served = consent_text(policy, "en", kind)
        assert served.source == "studio"
        assert served.language == "de"
        assert "Documentation body" in served.html
        assert "Guest release body" in served.html
        assert "Quality only" not in served.html
        assert served.accept_label == "Accept Guest release"
        assert served.documentation_consent["accept_label"] == "Accept Documentation"
        assert served.decline_label == "Decline Guest release"
        assert "synthetic-draft-1" in served.version


def test_statutory_notice_is_not_replaced_with_consent_to_another_legal_basis():
    from services.api_gateway.recording.consent_text import consent_text

    policy = runtime(legal_block()).policy.recording.model_copy(update={"legal_basis": "statutory"})
    served = consent_text(policy, "en", "first")
    assert "Documentation body" not in served.html
    assert "Guest release body" in served.html
    assert "gesetz" in served.html.lower()
    assert served.accept_label == "Accept Guest release"


async def test_employee_must_release_each_section_and_accepted_wording_is_archived(tmp_path):
    from services.api_gateway.recording.consent_evidence import ConsentEvidenceError
    from services.api_gateway.recording.consent_text import staff_release
    from services.api_gateway.recording.session_state import Phase
    from tests.recording_archive_fakes import say_yes
    from tests.test_recording_consent_capture import _consent_record
    from tests.test_recording_session_service import ADMIN, KEY, Harness

    h = Harness(tmp_path)
    h.policy = runtime(legal_block()).policy.recording
    release = staff_release(h.policy)
    with pytest.raises(ConsentEvidenceError, match="STAFF_RELEASE_TEXT_MISMATCH"):
        await h.service.request(KEY, request_id="missing", requested_by="emp")
    for request_id in ("first", "second"):
        await h.service.request(
            KEY, request_id=request_id, requested_by="emp", staff_release_sha256=release.sha256
        )
        state = await h.service.state(KEY)
        assert state.staff_release["sha256"] == release.sha256
        assert state.staff_release["html"] == release.html
        await say_yes(h.service, KEY, request_id)
        record = await _consent_record(h)
        assert record["staff_release"]["sha256"] == release.sha256
        assert record["staff_release"]["actor"] == "emp"
        await h.service.stop(KEY, role=ADMIN, actor="emp")
        assert (await h.service.state(KEY)).phase is Phase.OFF


async def test_employee_release_edit_invalidates_a_pending_guest_yes(tmp_path):
    from services.api_gateway.recording.consent_evidence import ConsentEvidenceError
    from services.api_gateway.recording.consent_text import staff_release
    from tests.recording_archive_fakes import say_yes
    from tests.test_recording_session_service import KEY, Harness

    h = Harness(tmp_path)
    h.policy = runtime(legal_block()).policy.recording
    release = staff_release(h.policy)
    await h.service.request(
        KEY, request_id="r1", requested_by="emp", staff_release_sha256=release.sha256
    )
    changed = legal_block()
    changed["localizations"][0]["staffRecordingRelease"]["bodyHtml"] = "<p>Changed release</p>"
    h.policy = runtime(changed).policy.recording
    with pytest.raises(ConsentEvidenceError, match="STAFF_RELEASE_TEXT_MISMATCH"):
        await say_yes(h.service, KEY, "r1")
    assert not h.rig.repository.entries


async def test_recording_release_alone_does_not_replace_documentation_consent(tmp_path):
    from services.api_gateway.recording.consent_evidence import ConsentEvidenceError
    from services.api_gateway.recording.consent_text import staff_release
    from tests.recording_archive_fakes import say_yes
    from tests.test_recording_session_service import KEY, Harness

    h = Harness(tmp_path)
    h.policy = runtime(legal_block()).policy.recording
    release = staff_release(h.policy)
    await h.service.request(
        KEY, request_id="r1", requested_by="emp", staff_release_sha256=release.sha256
    )
    with pytest.raises(ConsentEvidenceError, match="DOCUMENTATION_CONSENT_REQUIRED"):
        await say_yes(h.service, KEY, "r1", documentation_consent=False)
    assert not h.rig.repository.entries


@pytest.mark.parametrize("group", ["guestRecordingRelease", "mode2Consent"])
def test_guest_choice_label_edits_invalidate_an_answer_without_losing_html_digest(group):
    import hashlib

    from services.api_gateway.recording.consent_evidence import (
        ConsentEvidenceError,
        GuestAnswer,
        evidence,
    )
    from services.api_gateway.recording.consent_text import consent_text
    from services.api_gateway.recording.session_state import RecordingState

    before = runtime(legal_block()).policy.recording
    served = consent_text(before, "en", "first")
    changed = legal_block()
    changed["localizations"][0][group]["acceptLabel"] = "Changed affirmative choice"
    after = runtime(changed).policy.recording
    current = consent_text(after, "en", "first")
    assert current.sha256 == served.sha256 == hashlib.sha256(served.html.encode()).hexdigest()
    assert current.answer_sha256 != served.answer_sha256
    with pytest.raises(ConsentEvidenceError, match="CONSENT_TEXT_MISMATCH"):
        evidence(
            after,
            RecordingState(request_kind="first"),
            GuestAnswer("en", served.answer_sha256, name="Guest", documentation_consent=True),
        )


def test_legal_localization_prefers_matching_locale_over_source():
    from services.api_gateway.recording.consent_text import consent_text

    block = legal_block()
    translated = deepcopy(block["localizations"][0])
    translated["locale"] = "en-GB"
    translated["guestRecordingRelease"] = choice("English release")
    block["localizations"].append(translated)
    served = consent_text(runtime(block).policy.recording, "en", "first")
    assert served.language == "en"
    assert "English release body" in served.html
