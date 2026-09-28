"""Resolve Studio display fields for a conversation language without changing it."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

import nh3

from .speech_services import SpeechServices
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


_HTML_TAGS = {"p", "br", "strong", "em", "ul", "ol", "li", "a"}
_HTML_ATTRIBUTES = {"a": {"href"}}
_HTML_URL_SCHEMES = {"http", "https", "mailto"}
_WHITESPACE = re.compile(r"^(\s*)(.*?)(\s*)$", re.DOTALL)


def _safe_html(fragment: str) -> str:
    cleaned = nh3.clean(
        fragment,
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRIBUTES,
        url_schemes=_HTML_URL_SCHEMES,
        clean_content_tags={"script", "style"},
    )
    return cleaned if cleaned.strip() else html.escape(fragment)


class _HtmlTextNodes(HTMLParser):
    """Collect safe markup tokens and text nodes without translating markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = "".join(
            f' {name}="{html.escape(value or "", quote=True)}"' for name, value in attrs
        )
        self.tokens.append(("markup", f"<{tag}{attributes}>"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        self.tokens.append(("markup", f"</{tag}>"))

    def handle_data(self, data: str) -> None:
        self.tokens.append(("text", data))


def _translated_nodes(
    nodes: list[str], source_language: str, target_language: str, speech: SpeechServices
) -> list[str]:
    response = speech.translate(
        {"text": nodes, "source_lang": source_language, "target_lang": target_language}
    )
    response.raise_for_status()
    payload = response.json()
    translated = payload.get("translations") if isinstance(payload, dict) else None
    if (
        not isinstance(translated, list)
        or len(translated) != len(nodes)
        or any(not isinstance(value, str) or not value.strip() for value in translated)
    ):
        raise ValueError("translation returned unusable text")
    return translated


def resolve_field(
    selected: SelectedText, language: str, field: DisplayField, speech: SpeechServices
) -> str:
    """Translate one selected source, returning that safe source on failure."""
    if field.kind == "text":
        if selected.language == _primary_language(language):
            return selected.text
        try:
            return _translated_nodes(
                [selected.text], selected.language, _primary_language(language), speech
            )[0]
        except Exception:
            return selected.text

    try:
        source = _safe_html(selected.text)
    except Exception:
        source = html.escape(selected.text)
    if selected.language == _primary_language(language):
        return source

    parser = _HtmlTextNodes()
    try:
        parser.feed(source)
        parser.close()
        parts = [_WHITESPACE.fullmatch(value) for kind, value in parser.tokens if kind == "text"]
        nodes = [part.group(2) for part in parts if part is not None and part.group(2)]
        if not nodes:
            return source
        translated = iter(
            _translated_nodes(nodes, selected.language, _primary_language(language), speech)
        )
        output = []
        for kind, value in parser.tokens:
            if kind == "markup":
                output.append(value)
                continue
            part = _WHITESPACE.fullmatch(value)
            if part is None or not part.group(2):
                output.append(html.escape(value))
            else:
                output.append(html.escape(part.group(1) + next(translated) + part.group(3)))
        return _safe_html("".join(output))
    except Exception:
        return source


def resolve_display_texts(
    config: RuntimeConfiguration, language: str, speech: SpeechServices
) -> dict[str, str | None]:
    """Resolve the three known Studio display fields without changing language."""
    result: dict[str, str | None] = {}
    for field in DISPLAY_FIELDS.values():
        selected = select_source(config, language, field)
        result[field.name] = (
            None if selected is None else resolve_field(selected, language, field, speech)
        )
    return result
