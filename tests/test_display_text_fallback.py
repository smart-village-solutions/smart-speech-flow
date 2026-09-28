"""Behavior of the internal Studio display-text fallback."""

from __future__ import annotations

import pytest

from services.api_gateway.display_text_fallback import (
    DISPLAY_FIELDS,
    SelectedText,
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
    config = make_config(
        [("de-DE", {field_name: "German"}), ("sw-KE", {field_name: "Reviewed"})]
    )

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText(
        "Reviewed", "sw"
    )


@pytest.mark.parametrize("field_name", FIELDS)
def test_german_studio_source_wins_for_each_field(field_name: str) -> None:
    config = make_config(
        [("de-DE", {field_name: "German"}), ("en-US", {field_name: "English"})]
    )

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText(
        "German", "de"
    )


@pytest.mark.parametrize("field_name", FIELDS)
def test_english_studio_source_is_next_for_each_field(field_name: str) -> None:
    config = make_config(
        [("fr-FR", {field_name: " "}), ("en-US", {field_name: "English"})]
    )

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText(
        "English", "en"
    )


@pytest.mark.parametrize("field_name", FIELDS)
def test_ssf_english_default_is_last_for_each_field(field_name: str) -> None:
    config = make_config([("fr-FR", {})])

    assert select_source(config, "sw", DISPLAY_FIELDS[field_name]) == SelectedText(
        DISPLAY_FIELDS[field_name].english_default, "en"
    )


def test_exact_tag_wins_over_default_regional_variant() -> None:
    config = make_config(
        [("de-DE", {"guestExplanationHtml": "German"}),
         ("en-GB", {"guestExplanationHtml": "British"}),
         ("en-US", {"guestExplanationHtml": "American"})],
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
        [("de-DE", {"guestExplanationHtml": "German"}),
         ("en-GB", {"guestExplanationHtml": ""}),
         ("en-US", {"guestExplanationHtml": "American"})]
    )

    assert select_source(config, "en", DISPLAY_FIELDS["guestExplanationHtml"]) == SelectedText(
        "American", "en"
    )


def test_disabled_storage_never_gets_a_fallback_question() -> None:
    config = make_config([("de-DE", {})], storage_mode="disabled")

    assert select_source(
        config, "sw", DISPLAY_FIELDS["conversationContentStorageQuestionHtml"]
    ) is None
