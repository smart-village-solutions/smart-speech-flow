"""The consent text a guest is shown, as the gateway serves it (spec §6, D9).

Studio's text for the guest's language wins; otherwise the bundled text for the
tenant's legal basis applies. Both are sanitised here, and the hash covers the
exact string served, so the evidence never depends on what a browser sends.
"""

from __future__ import annotations

import functools
import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import nh3

from ..studio_html import safe_html
from ..studio_locales import ssf_language
from ..studio_v2 import RecordingPolicy, RecordingTexts
from .session_state import ConsentKind

# Bump with any change to a file in consent_texts/: archived records cite it.
BUNDLED_VERSION: Final[str] = "bundled-1"
GERMAN: Final[str] = "de"
_BUNDLED_DIRECTORY: Final[Path] = Path(__file__).with_name("consent_texts")
_BREAKS: Final[re.Pattern[str]] = re.compile(r"</p>|</li>|<br\s?/?>")

Source = Literal["studio", "bundled"]


@dataclass(frozen=True, slots=True)
class ConsentText:
    language: str
    kind: ConsentKind
    source: Source
    version: str
    html: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.html.encode()).hexdigest()

    def record(self) -> dict[str, str]:
        return {
            "language": self.language,
            "kind": self.kind,
            "source": self.source,
            "version": self.version,
            "sha256": self.sha256,
            "html": self.html,
        }

    def plain(self) -> str:
        """The words alone, one paragraph per line, for reading aloud."""
        text = nh3.clean(_BREAKS.sub("\n", self.html), tags=set())
        lines = (" ".join(line.split()) for line in html.unescape(text).splitlines())
        return "\n".join(line for line in lines if line)


@functools.cache
def _bundled(language: str) -> dict[str, dict[str, str]] | None:
    path = _BUNDLED_DIRECTORY / f"{language}.json"
    if not path.is_file():
        return None
    texts: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return texts


def _language(locale: str) -> str | None:
    if locale.split("-", 1)[0].lower() == GERMAN:
        return GERMAN
    return ssf_language(locale)


def _studio(policy: RecordingPolicy, language: str) -> RecordingTexts | None:
    """The first entry for the language; a later one that maps alike is ignored."""
    return next((t for t in policy.texts if _language(t.locale) == language), None)


def consent_text(policy: RecordingPolicy, language: str, kind: ConsentKind) -> ConsentText:
    # The guest's language arrives unchecked from activation, and names a file below.
    language = _language(language) or GERMAN
    studio = _studio(policy, language)
    if studio is not None:
        markup = studio.consent_html if kind == "first" else studio.resume_prompt_html
        return ConsentText(
            language, kind, "studio", policy.configuration_revision, safe_html(markup)
        )
    bundled = _bundled(language)
    if bundled is None:
        language, bundled = GERMAN, _bundled(GERMAN)
    if bundled is None:
        raise RuntimeError("The bundled German consent text is missing")
    markup = bundled[policy.legal_basis][kind]
    return ConsentText(language, kind, "bundled", BUNDLED_VERSION, safe_html(markup))


def german_text(policy: RecordingPolicy, served: ConsentText) -> ConsentText:
    """The German text of the same version: Studio's if Studio served the guest's text."""
    if served.source == "studio" and _studio(policy, GERMAN) is not None:
        return consent_text(policy, GERMAN, served.kind)
    return consent_text(policy.model_copy(update={"texts": ()}), GERMAN, served.kind)
