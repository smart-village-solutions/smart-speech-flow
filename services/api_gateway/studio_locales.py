"""Studio guest locales mapped onto SSF's own guest languages.

SSF keeps its own list. Studio content only replaces bundled copy for a
language on that list, and the staff language is never offered to guests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal

from .message_models import SUPPORTED_LANGUAGES
from .studio_v2 import GuestLanguageContent

STAFF_LANGUAGE = "de"
GUEST_LANGUAGES = tuple(code for code in SUPPORTED_LANGUAGES if code != STAFF_LANGUAGE)
# Studio's locale for a language SSF knows under another code.
LOCALE_ALIASES = {"kmr": "ku"}

SkipReason = Literal["unsupported", "duplicate"]
SKIP_REASONS: tuple[SkipReason, ...] = ("unsupported", "duplicate")


def ssf_language(locale: str) -> str | None:
    """SSF's guest language for a BCP 47 locale, by primary subtag, or None."""
    primary = locale.split("-", 1)[0].lower()
    code = LOCALE_ALIASES.get(primary, primary)
    return code if code in GUEST_LANGUAGES else None


def guest_languages_by_code(
    languages: Iterable[GuestLanguageContent],
    on_skip: Callable[[SkipReason], None],
) -> dict[str, GuestLanguageContent]:
    """Key Studio's guest languages by SSF code; the first of two that map alike wins."""
    mapped: dict[str, GuestLanguageContent] = {}
    for language in languages:
        code = ssf_language(language.locale)
        if code is None:
            on_skip("unsupported")
        elif code in mapped:
            on_skip("duplicate")
        else:
            mapped[code] = language
    return mapped
