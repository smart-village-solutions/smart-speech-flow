"""Read-only legal information must not alter the live storage/activation contract."""

from __future__ import annotations

from copy import deepcopy

import pytest

from services.api_gateway.content_responses import guest_content_response, staff_content_response
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_content_service import GuestContent
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
    body = guest_content_response(GuestContent("ask", content), "xx").model_dump(by_alias=True)
    assert body["provided"] is False
    assert body["storage"] == {"mode": "ask"}
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
    guest = guest_content_response(GuestContent("ask", content), "en").model_dump(by_alias=True)
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
    information = guest_content_response(GuestContent("ask", content), "en").model_dump(
        by_alias=True
    )["legalInformation"]
    assert information is not None
    assert information["locale"] == "de-DE"
    assert information["sections"][0]["headline"] == "Documentation"


@pytest.mark.parametrize(
    "translated_field", ["mode3Consent", "mode2Consent", "guestRecordingRelease"]
)
def test_partial_translation_uses_complete_source_documentation_without_changing_reference(
    translated_field,
):
    block = legal_block()
    translated_choice = deepcopy(block["localizations"][0][translated_field])
    translated_choice["headline"] = "Translated partial wording"
    block["localizations"].append({"locale": "en-GB", translated_field: translated_choice})
    content = StudioContentCache().record(read(block))
    body = guest_content_response(GuestContent("ask", content), "en").model_dump(by_alias=True)

    assert body["legalInformation"]["locale"] == "en-GB"
    assert [part["id"] for part in body["legalInformation"]["sections"]] == [translated_field]
    assert body["documentationInformation"] == {
        "locale": "de-DE",
        "version": "synthetic-draft",
        "sections": [
            {
                "id": "mode2Consent",
                "headline": "Documentation",
                "bodyHtml": "<p>Documentation body</p>",
            },
            {
                "id": "guestRecordingRelease",
                "headline": "Guest release",
                "bodyHtml": "<p>Guest release body</p>",
            },
        ],
    }


@pytest.mark.parametrize("requested_locale", ["en", "EN-gb", "en-US"])
def test_complete_translated_documentation_pair_keeps_its_actual_locale(requested_locale):
    block = legal_block()
    entry = deepcopy(block["localizations"][0])
    entry["locale"] = "en-GB"
    entry["mode2Consent"]["headline"] = "Translated documentation"
    entry["guestRecordingRelease"]["headline"] = "Translated guest release"
    block["localizations"].append(entry)
    content = StudioContentCache().record(read(block))
    body = guest_content_response(GuestContent("ask", content), requested_locale).model_dump(
        by_alias=True
    )

    information = body["documentationInformation"]
    assert (information["locale"], information["version"]) == ("en-GB", "synthetic-draft")
    assert [(part["id"], part["headline"]) for part in information["sections"]] == [
        ("mode2Consent", "Translated documentation"),
        ("guestRecordingRelease", "Translated guest release"),
    ]
    assert all(set(part) == {"id", "headline", "bodyHtml"} for part in information["sections"])
    assert "Never render" not in str(information)


@pytest.mark.parametrize("source_missing", ["mode2Consent", "guestRecordingRelease"])
def test_incomplete_source_never_combines_with_partial_translation(source_missing):
    block = legal_block()
    source = block["localizations"][0]
    translated_choice = source.pop(source_missing)
    block["localizations"].append({"locale": "en-GB", source_missing: translated_choice})
    content = StudioContentCache().record(read(block))
    body = guest_content_response(GuestContent("ask", content), "en").model_dump(by_alias=True)

    assert body["documentationInformation"] is None
    assert body["legalInformation"]["locale"] == "en-GB"
    assert (
        guest_content_response(GuestContent("ask", content), "de-DE").model_dump(by_alias=True)[
            "documentationInformation"
        ]
        is None
    )


@pytest.mark.parametrize("language", ["en", "fa"])
def test_absent_legal_texts_return_null_documentation_for_all_guest_content(language):
    content = StudioContentCache().record(read())
    body = guest_content_response(GuestContent("ask", content), language).model_dump(by_alias=True)
    assert body["documentationInformation"] is None
    assert (
        guest_content_response(GuestContent("ask", None), language).model_dump(by_alias=True)[
            "documentationInformation"
        ]
        is None
    )


@pytest.mark.parametrize("document", ["mode2Consent", "guestRecordingRelease"])
@pytest.mark.parametrize(
    ("field", "empty_wording"),
    [
        ("headline", " \t\n\u00a0"),
        ("bodyHtml", "<p><br></p>"),
        ("bodyHtml", "<p>&nbsp;</p>"),
        ("bodyHtml", "<p>&#160; &#x20;</p>"),
        ("bodyHtml", "<p> \t\n</p>"),
    ],
)
def test_visually_empty_translated_document_uses_complete_source_pair(
    document, field, empty_wording
):
    block = legal_block()
    translated = deepcopy(block["localizations"][0])
    translated["locale"] = "en-GB"
    translated[document][field] = empty_wording
    block["localizations"].append(translated)
    content = StudioContentCache().record(read(block))
    body = guest_content_response(GuestContent("ask", content), "en").model_dump(by_alias=True)

    assert body["legalInformation"]["locale"] == "en-GB"
    reference = next(
        part for part in body["legalInformation"]["sections"] if part["id"] == document
    )
    assert reference[field] == empty_wording.replace("&#160;", "&nbsp;").replace("&#x20;", " ")
    information = body["documentationInformation"]
    assert (information["locale"], information["version"]) == ("de-DE", "synthetic-draft")
    assert [(part["id"], part["headline"]) for part in information["sections"]] == [
        ("mode2Consent", "Documentation"),
        ("guestRecordingRelease", "Guest release"),
    ]


@pytest.mark.parametrize("document", ["mode2Consent", "guestRecordingRelease"])
@pytest.mark.parametrize(
    ("field", "empty_wording"),
    [("headline", " \t\n\u00a0"), ("bodyHtml", "<p><br>&nbsp;</p>")],
)
def test_visually_empty_source_document_cannot_supply_a_documentation_pair(
    document, field, empty_wording
):
    block = legal_block()
    block["localizations"][0][document][field] = empty_wording
    content = StudioContentCache().record(read(block))

    for locale in ("de-DE", "en"):
        body = guest_content_response(GuestContent("ask", content), locale).model_dump(
            by_alias=True
        )
        assert body["documentationInformation"] is None
        assert body["legalInformation"]["locale"] == "de-DE"


@pytest.mark.parametrize("document", ["mode2Consent", "guestRecordingRelease"])
@pytest.mark.parametrize(
    "body_html",
    ["<p>„…“ — العربية • 中文 &amp; €</p>", "<p>&lt;script&gt;literal&lt;/script&gt;</p>"],
)
def test_visible_unicode_and_escaped_literal_documentation_is_preserved(document, body_html):
    block = legal_block()
    translated = deepcopy(block["localizations"][0])
    translated["locale"] = "en-GB"
    translated[document]["bodyHtml"] = body_html
    block["localizations"].append(translated)
    content = StudioContentCache().record(read(block))
    information = guest_content_response(GuestContent("ask", content), "en").model_dump(
        by_alias=True
    )["documentationInformation"]

    assert information["locale"] == "en-GB"
    section = next(part for part in information["sections"] if part["id"] == document)
    assert section["bodyHtml"] == body_html
