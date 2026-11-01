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
from typing import Any, Final, Literal

import nh3

from ..studio_html import safe_html
from ..studio_legal import LegalChoice, legal_localization
from ..studio_locales import ssf_language
from ..studio_v2 import RecordingPolicy, RecordingTexts
from .session_state import ConsentKind

# Bump with any change to a file in consent_texts/: archived records cite it.
BUNDLED_VERSION: Final[str] = "bundled-2"
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
    accept_label: str | None = None
    decline_label: str | None = None
    documentation_consent: dict[str, str] | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.html.encode()).hexdigest()

    @property
    def answer_sha256(self) -> str:
        if (
            self.accept_label is None
            and self.decline_label is None
            and self.documentation_consent is None
        ):
            return self.sha256
        fields = {
            "html": self.html,
            "language": self.language,
            "version": self.version,
            "accept_label": self.accept_label,
            "decline_label": self.decline_label,
            "documentation_consent": self.documentation_consent,
        }
        return hashlib.sha256(
            json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def record(self) -> dict[str, Any]:
        return {
            **({"answer_sha256": self.answer_sha256} if self.answer_sha256 != self.sha256 else {}),
            **(
                {"documentation_consent": self.documentation_consent}
                if self.documentation_consent
                else {}
            ),
            **({"accept_label": self.accept_label} if self.accept_label else {}),
            **({"decline_label": self.decline_label} if self.decline_label else {}),
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


def _legacy_consent_text(policy: RecordingPolicy, language: str, kind: ConsentKind) -> ConsentText:
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


def _choice_html(choice: LegalChoice) -> str:
    return safe_html(f"<p><strong>{html.escape(choice.headline)}</strong></p>{choice.body_html}")


def consent_text(policy: RecordingPolicy, language: str, kind: ConsentKind) -> ConsentText:
    entry = legal_localization(policy.legal_texts, language)
    if entry is None:
        return _legacy_consent_text(policy, language, kind)
    consent = entry.mode2_consent if policy.legal_basis == "consent" else None
    release = entry.guest_recording_release
    if consent is None and release is None:
        return _legacy_consent_text(policy, language, kind)
    actual_language = _language(entry.locale) or entry.locale.split("-", 1)[0].lower()
    # Without replacement consent wording, retain the existing legal-basis notice.
    # Renewals repeat the full documentation consent so changed wording is reviewed.
    notice = (
        _choice_html(consent)
        if consent is not None
        else _legacy_consent_text(policy, actual_language, kind).html
    )
    markup = notice + (_choice_html(release) if release is not None else "")
    selected = release or consent
    assert selected is not None and policy.legal_texts is not None
    return ConsentText(
        actual_language,
        kind,
        "studio",
        policy.legal_texts.version,
        safe_html(markup),
        selected.accept_label,
        selected.decline_label,
        (
            {"accept_label": consent.accept_label, "decline_label": consent.decline_label}
            if consent is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class StaffRelease:
    language: str
    html: str
    accept_label: str
    decline_label: str
    version: str

    @property
    def sha256(self) -> str:
        # Choice labels and version are part of the employee's affirmative action.
        return hashlib.sha256(
            json.dumps(self._fields(), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def _fields(self) -> dict[str, str]:
        return {
            "language": self.language,
            "html": self.html,
            "accept_label": self.accept_label,
            "decline_label": self.decline_label,
            "version": self.version,
        }

    def record(self) -> dict[str, str]:
        return self._fields() | {"sha256": self.sha256}


def staff_release(policy: RecordingPolicy) -> StaffRelease | None:
    entry = legal_localization(policy.legal_texts, GERMAN)
    choice = entry.staff_recording_release if entry is not None else None
    if choice is None or entry is None or policy.legal_texts is None:
        return None
    language = entry.locale.split("-", 1)[0].lower()
    return StaffRelease(
        language,
        _choice_html(choice),
        choice.accept_label,
        choice.decline_label,
        policy.legal_texts.version,
    )


def german_text(policy: RecordingPolicy, served: ConsentText) -> ConsentText:
    """The German text of the same version: Studio's if Studio served the guest's text."""
    if served.source == "studio" and policy.legal_texts is not None:
        return consent_text(policy, GERMAN, served.kind)
    if served.source == "studio" and _studio(policy, GERMAN) is not None:
        return consent_text(policy, GERMAN, served.kind)
    return consent_text(policy.model_copy(update={"texts": ()}), GERMAN, served.kind)
