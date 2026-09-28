"""Resolve Studio display fields for a conversation language without changing it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .studio_runtime_client import LocaleConfiguration, RuntimeConfiguration


@dataclass(frozen=True)
class DisplayField:
    name: str
    attribute: str
    kind: Literal["text", "html"]
    english_default: str


@dataclass(frozen=True)
class SelectedText:
    text: str
    language: str


_EXPLANATION_DEFAULT = "<p>Smart Speech Flow helps people communicate across languages.</p>"

DISPLAY_FIELDS = {
    "authenticatedHomeExplanationHtml": DisplayField(
        "authenticatedHomeExplanationHtml",
        "authenticated_home_explanation_html",
        "html",
        _EXPLANATION_DEFAULT,
    ),
    "guestExplanationHtml": DisplayField(
        "guestExplanationHtml", "guest_explanation_html", "html", _EXPLANATION_DEFAULT
    ),
    "conversationContentStorageQuestionHtml": DisplayField(
        "conversationContentStorageQuestionHtml",
        "conversation_content_storage_question_html",
        "html",
        "<p>May this conversation be stored?</p>",
    ),
}


def _primary_language(tag: str) -> str:
    return tag.split("-", 1)[0].casefold()


def _present_text(entry: LocaleConfiguration, field: DisplayField) -> bool:
    value = getattr(entry, field.attribute, None)
    return isinstance(value, str) and bool(value.strip())


def _matching_locale(
    config: RuntimeConfiguration, tag: str, field: DisplayField
) -> LocaleConfiguration | None:
    locales = [entry for entry in config.localization.locales if _present_text(entry, field)]
    exact = next((entry for entry in locales if entry.locale.casefold() == tag.casefold()), None)
    if exact is not None:
        return exact
    same_language = [
        entry for entry in locales if _primary_language(entry.locale) == _primary_language(tag)
    ]
    return next(
        (
            entry
            for entry in same_language
            if entry.locale.casefold() == config.localization.default_locale.casefold()
        ),
        None,
    ) or (same_language[0] if same_language else None)


def select_source(
    config: RuntimeConfiguration, language: str, field: DisplayField
) -> SelectedText | None:
    """Select reviewed Studio text or the SSF English display default per field."""
    if (
        field.name == "conversationContentStorageQuestionHtml"
        and config.conversation_content_storage.mode == "disabled"
    ):
        return None

    for candidate in (language, "de", "en"):
        entry = _matching_locale(config, candidate, field)
        if entry is not None:
            return SelectedText(getattr(entry, field.attribute), _primary_language(entry.locale))
    return SelectedText(field.english_default, "en")
