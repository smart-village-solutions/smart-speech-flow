"""Read-only legal information must not alter the live storage/activation contract."""

from __future__ import annotations

from copy import deepcopy

from services.api_gateway.content_responses import guest_content_response, staff_content_response
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_v2 import parse_runtime_configuration_v2
from tests.studio_v2_fixtures import KASSEL, load_fixture


def legal_block() -> dict:
    def choice(name):
        return {
            "headline": name,
            "bodyHtml": f'<p onclick="bad()">{name} body</p><script>hidden()</script>',
            "acceptLabel": "Never render as a button",
            "declineLabel": "Never render as a button either",
        }

    return {
        "sourceLocale": "de-DE",
        "version": "synthetic-draft",
        "localizations": [
            {
                "locale": "de-DE",
                "mode2Consent": choice("Documentation"),
                "mode3Consent": choice("Quality"),
                "guestRecordingRelease": choice("Guest release"),
                "staffRecordingRelease": choice("Staff release"),
                "recordingStatus": None,
            }
        ],
    }


def read(block=None, tenant="tenant-kassel"):
    body = load_fixture(KASSEL)
    body["tenant"]["id"] = tenant
    if block is not None:
        body["legalTexts"] = block
    return parse_runtime_configuration_v2(body, expected_tenant_id=tenant)


def test_optional_legal_information_preserves_policy_and_legacy_content():
    old, new = read(), read(legal_block())
    assert old.policy == new.policy
    assert old.content.model_dump(exclude={"legal_texts"}) == new.content.model_dump(
        exclude={"legal_texts"}
    )
    assert new.content.legal_texts.version == "synthetic-draft"


def test_guest_information_is_independent_of_guest_language_coverage():
    content = StudioContentCache().record(read(legal_block()))
    body = guest_content_response(content, "xx").model_dump(by_alias=True)
    assert body["provided"] is False
    assert "storage" not in body
    information = body["legalInformation"]
    assert (information["locale"], information["version"]) == ("de-DE", "synthetic-draft")
    assert [section["id"] for section in information["sections"]] == [
        "mode2Consent",
        "mode3Consent",
        "guestRecordingRelease",
        "staffRecordingRelease",
    ]
    assert information["sections"][0] == {
        "id": "mode2Consent",
        "headline": "Documentation",
        "bodyHtml": "<p>Documentation body</p>",
    }
    assert "Never render" not in str(information)


def test_staff_information_and_source_fallback_stay_tenant_scoped():
    cache = StudioContentCache()
    kassel = cache.record(read(legal_block()))
    other = cache.record(read(tenant="other-tenant"))
    assert (
        staff_content_response(kassel).model_dump(by_alias=True)["legalInformation"]["locale"]
        == "de-DE"
    )
    assert staff_content_response(other).model_dump(by_alias=True)["legalInformation"] is None


def test_a_matching_translation_wins_and_invalid_legal_data_only_drops_information():
    block = legal_block()
    entry = deepcopy(block["localizations"][0])
    entry["locale"] = "en-GB"
    entry["mode2Consent"]["headline"] = "English documentation"
    block["localizations"].append(entry)
    cache = StudioContentCache()
    content = cache.record(read(block))
    guest = guest_content_response(content, "en").model_dump(by_alias=True)
    assert guest["legalInformation"]["locale"] == "en-GB"
    block["sourceLocale"] = "fr"
    invalid = read(block)
    assert invalid.policy == read().policy
    assert invalid.content.legal_texts is None


def test_status_only_localization_falls_back_to_source_information():
    block = legal_block()
    block["localizations"].append(
        {
            "locale": "en-GB",
            "recordingStatus": {
                "waiting": "Waiting",
                "running": "Running",
                "stopped": "Stopped",
                "renewedReleaseRequired": "Release again",
            },
        }
    )
    content = StudioContentCache().record(read(block))
    information = guest_content_response(content, "en").model_dump(by_alias=True)[
        "legalInformation"
    ]
    assert information is not None
    assert information["locale"] == "de-DE"
    assert information["sections"][0]["headline"] == "Documentation"
