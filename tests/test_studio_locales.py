"""Studio guest locales mapped onto SSF's own guest languages."""

from __future__ import annotations

import pytest

from services.api_gateway.studio_locales import (
    GUEST_LANGUAGES,
    guest_languages_by_code,
    ssf_language,
)
from services.api_gateway.studio_v2 import GuestLanguageContent


def language(locale: str) -> GuestLanguageContent:
    return GuestLanguageContent.model_validate(
        {
            "locale": locale,
            "nativeName": f"native {locale}",
            "staffName": f"staff {locale}",
            "icon": None,
            "guest": {"explanationHtml": "<p>x</p>"},
        }
    )


def test_guest_languages_are_ssfs_own_without_the_staff_language() -> None:
    assert GUEST_LANGUAGES == (
        "en", "ar", "tr", "ru", "uk", "am", "fa",
        "it", "ro", "pl", "bg", "el", "fr", "es", "pt", "sq", "hu", "zh", "hi",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("locale", "code"),
    [
        ("en", "en"),
        ("en-GB", "en"),
        ("EN-us", "en"),
        ("kmr", None),
        ("ku-Arab", None),
        ("fa-IR", "fa"),
        ("pt-BR", "pt"),
        ("zh-Hans-CN", "zh"),
    ],
)
def test_maps_by_primary_subtag_and_alias(locale: str, code: str | None) -> None:
    assert ssf_language(locale) == code


@pytest.mark.parametrize(
    "locale", ["de", "de-DE", "hr", "ckb", "zz", "ti", "ti-ER", "ku", "kmr-TR"]
)
def test_locales_ssf_does_not_offer_guests_have_no_code(locale: str) -> None:
    assert ssf_language(locale) is None


def test_skips_and_reports_unsupported_and_duplicate_locales() -> None:
    skipped: list[str] = []

    mapped = guest_languages_by_code(
        [language("en"), language("hr"), language("kmr"), language("en-GB"), language("de")],
        skipped.append,
    )

    assert list(mapped) == ["en"]
    assert mapped["en"].locale == "en"
    assert skipped == ["unsupported", "unsupported", "duplicate", "unsupported"]
