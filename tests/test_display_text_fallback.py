"""Behavior of the internal Studio display-text fallback."""

from __future__ import annotations

import pytest

from services.api_gateway.display_text_fallback import (
    DISPLAY_FIELDS,
    DisplayField,
    SelectedText,
    resolve_display_texts,
    resolve_field,
    select_source,
)
from services.api_gateway.studio_runtime_client import RuntimeConfiguration

REVISION = "sha256:" + "a" * 64
FIELDS = (
    "authenticatedHomeExplanationHtml",
    "guestExplanationHtml",
    "conversationContentStorageQuestionHtml",
)


def make_config(
    locales: list[tuple[str, dict[str, str | None]]],
    *,
    default_locale: str | None = None,
    storage_mode: str = "ask",
) -> RuntimeConfiguration:
    entries = []
    for locale, values in locales:
        entry: dict[str, str | None] = {
            "locale": locale,
            "authenticatedHomeExplanationHtml": "",
            "guestExplanationHtml": "",
            "conversationContentStorageQuestionHtml": None,
        }
        entry.update(values)
        entries.append(entry)
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {
                "id": "tenant-test",
                "displayName": "Test Tenant",
                "timeZone": "Europe/Berlin",
            },
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": default_locale or entries[0]["locale"],
                "locales": entries,
            },
            "conversationContentStorage": {"mode": storage_mode},
        }
    )


@pytest.mark.parametrize("field_name", FIELDS)
def test_matching_reviewed_studio_text_wins_for_each_field(field_name: str) -> None:
    config = make_config([("de-DE", {field_name: "German"}), ("sw-KE", {field_name: "Reviewed"})])

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText("Reviewed", "sw")


@pytest.mark.parametrize("field_name", FIELDS)
def test_german_studio_source_wins_for_each_field(field_name: str) -> None:
    config = make_config([("de-DE", {field_name: "German"}), ("en-US", {field_name: "English"})])

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText("German", "de")


@pytest.mark.parametrize("field_name", FIELDS)
def test_english_studio_source_is_next_for_each_field(field_name: str) -> None:
    config = make_config([("fr-FR", {field_name: " "}), ("en-US", {field_name: "English"})])

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText("English", "en")


@pytest.mark.parametrize("field_name", FIELDS)
def test_ssf_english_default_is_last_for_each_field(field_name: str) -> None:
    config = make_config([("fr-FR", {})])

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText(
        DISPLAY_FIELDS[field_name].english_default, "en"
    )


def test_exact_tag_wins_over_default_regional_variant() -> None:
    config = make_config(
        [
            ("de-DE", {"guestExplanationHtml": "German"}),
            ("en-GB", {"guestExplanationHtml": "British"}),
            ("en-US", {"guestExplanationHtml": "American"}),
        ],
        default_locale="en-GB",
    )

    assert select_source(config, "EN-us", DISPLAY_FIELDS["guestExplanationHtml"]) == SelectedText(
        "American", "en"
    )
    assert select_source(config, "en", DISPLAY_FIELDS["guestExplanationHtml"]) == SelectedText(
        "British", "en"
    )


def test_first_present_regional_variant_is_used_without_same_language_default() -> None:
    config = make_config(
        [
            ("de-DE", {"guestExplanationHtml": "German"}),
            ("en-GB", {"guestExplanationHtml": ""}),
            ("en-US", {"guestExplanationHtml": "American"}),
        ]
    )

    assert select_source(config, "en", DISPLAY_FIELDS["guestExplanationHtml"]) == SelectedText(
        "American", "en"
    )


def test_disabled_storage_never_gets_a_fallback_question() -> None:
    config = make_config([("de-DE", {})], storage_mode="disabled")

    assert (
        select_source(config, "sw", DISPLAY_FIELDS["conversationContentStorageQuestionHtml"])
        is None
    )


class FakeResponse:
    def __init__(self, translations: list[str] | str) -> None:
        self.translations = translations

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, list[str] | str]:
        return {"translations": self.translations}


class RecordingSpeech:
    def __init__(
        self, *, fail: bool = False, invalid: bool = False, injected: bool = False
    ) -> None:
        self.fail = fail
        self.invalid = invalid
        self.injected = injected
        self.calls: list[dict[str, object]] = []

    def translate(self, payload: dict[str, object]) -> FakeResponse:
        self.calls.append(payload)
        if self.fail:
            raise ValueError("translation is unsupported")
        texts = payload["text"]
        assert isinstance(texts, list)
        if self.invalid:
            return FakeResponse([" "])
        if self.injected:
            return FakeResponse(["<img src=x onerror=evil()>" for _ in texts])
        return FakeResponse([f"translated:{text}" for text in texts])


@pytest.mark.parametrize("field_name", FIELDS)
@pytest.mark.parametrize(
    ("locales", "expected_source", "source_language"),
    [
        ([("de-DE", "German"), ("en-US", "English")], "German", "de"),
        ([("fr-FR", ""), ("en-US", "English")], "English", "en"),
        ([("fr-FR", "")], None, "en"),
    ],
)
def test_translates_each_field_from_selected_source(
    field_name: str,
    locales: list[tuple[str, str]],
    expected_source: str | None,
    source_language: str,
) -> None:
    config = make_config(
        [(tag, {field_name: f"<p>{value}</p>" if value else ""}) for tag, value in locales]
    )
    speech = RecordingSpeech()

    resolved = resolve_display_texts(config, "sw", speech)

    source = expected_source or DISPLAY_FIELDS[field_name].english_default.removeprefix(
        "<p>"
    ).removesuffix("</p>")
    assert resolved[field_name] == f"<p>translated:{source}</p>"
    assert any(
        call["source_lang"] == source_language
        and call["target_lang"] == "sw"
        and source in call["text"]
        for call in speech.calls
    )


@pytest.mark.parametrize("field_name", FIELDS)
def test_translation_failure_returns_selected_source_for_each_field(field_name: str) -> None:
    config = make_config([("de-DE", {field_name: "<p>German source</p>"})])

    resolved = resolve_display_texts(config, "sw", RecordingSpeech(fail=True))

    assert resolved[field_name] == "<p>German source</p>"


def test_matching_reviewed_text_skips_translation_and_keeps_language_selection() -> None:
    config = make_config([("de-DE", {}), ("sw-KE", {"guestExplanationHtml": "<p>Reviewed</p>"})])
    speech = RecordingSpeech()

    resolved = resolve_display_texts(config, "sw", speech)

    assert resolved["guestExplanationHtml"] == "<p>Reviewed</p>"
    assert config.localization.default_locale == "de-DE"
    assert all(call["target_lang"] == "sw" for call in speech.calls)


def test_html_translation_preserves_structure_and_excludes_markup_from_payload() -> None:
    html = (
        '<p onclick="evil()"><strong>German</strong> '
        '<a href="https://example.org" onclick="evil()">link</a>'
        '<a href="javascript:evil()">unsafe</a><script>evil()</script></p>'
    )
    config = make_config([("de-DE", {"guestExplanationHtml": html})])
    speech = RecordingSpeech()

    resolved = resolve_display_texts(config, "sw", speech)["guestExplanationHtml"]

    assert resolved is not None
    assert "<strong>translated:German</strong>" in resolved
    assert 'href="https://example.org"' in resolved
    assert "javascript:" not in resolved
    assert "onclick" not in resolved
    assert "<script" not in resolved
    assert all("<" not in text for call in speech.calls for text in call["text"])


def test_invalid_translation_result_returns_whole_safe_source_fragment() -> None:
    html = '<p><strong>German</strong> <a href="https://example.org">link</a></p>'
    config = make_config([("de-DE", {"guestExplanationHtml": html})])

    resolved = resolve_display_texts(config, "sw", RecordingSpeech(invalid=True))

    assert resolved["guestExplanationHtml"] == (
        '<p><strong>German</strong> <a href="https://example.org" '
        'rel="noopener noreferrer">link</a></p>'
    )


def test_disabled_storage_question_makes_no_translation_request() -> None:
    config = make_config([("de-DE", {})], storage_mode="disabled")
    speech = RecordingSpeech()

    resolved = resolve_display_texts(config, "sw", speech)

    assert resolved["conversationContentStorageQuestionHtml"] is None
    assert len(speech.calls) == 2


def test_plain_text_field_is_translated_without_html_parsing() -> None:
    field = DisplayField("plain", "plain", "text", "Plain English")
    speech = RecordingSpeech()

    result = resolve_field(SelectedText("Hello <world>", "en"), "sw", field, speech)

    assert result == "translated:Hello <world>"
    assert speech.calls[0]["text"] == ["Hello <world>"]


def test_unsafe_only_html_never_resolves_to_empty_text() -> None:
    config = make_config([("de-DE", {"guestExplanationHtml": "<script>unsafe()</script>"})])

    resolved = resolve_display_texts(config, "de", RecordingSpeech())

    assert resolved["guestExplanationHtml"] == "&lt;script&gt;unsafe()&lt;/script&gt;"


def test_generated_markup_is_displayed_as_text_not_executed() -> None:
    config = make_config([("de-DE", {"guestExplanationHtml": "<p>German</p>"})])

    resolved = resolve_display_texts(config, "sw", RecordingSpeech(injected=True))

    assert resolved["guestExplanationHtml"] == ("<p>&lt;img src=x onerror=evil()&gt;</p>")
