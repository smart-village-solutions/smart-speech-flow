"""Read-only legal wording: content only, never a consent or recording capability."""

from __future__ import annotations

from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .studio_legal import LegalChoice, LegalTexts, legal_localization


class _InformationModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LegalInformationSection(_InformationModel):
    id: str
    headline: str
    body_html: str


class LegalInformation(_InformationModel):
    locale: str
    version: str
    sections: list[LegalInformationSection]


_GROUPS = (
    ("mode2Consent", "mode2_consent"),
    ("mode3Consent", "mode3_consent"),
    ("guestRecordingRelease", "guest_recording_release"),
    ("staffRecordingRelease", "staff_recording_release"),
)


def legal_information(legal: LegalTexts | None, locale: str) -> LegalInformation | None:
    """Expose only sanitized wording and provenance, without actionable choice labels."""
    entry = legal_localization(legal, locale)
    if entry is None or legal is None:
        return None
    sections = []
    for identifier, field in _GROUPS:
        choice = getattr(entry, field)
        if choice is not None:
            sections.append(
                LegalInformationSection(
                    id=identifier, headline=choice.headline, body_html=choice.body_html
                )
            )
    if not sections and entry.locale.casefold() != legal.source_locale.casefold():
        return legal_information(legal, legal.source_locale)
    if not sections:
        return None
    return LegalInformation(locale=entry.locale, version=legal.version, sections=sections)


_DOCUMENTATION_GROUPS = (
    ("mode2Consent", "mode2_consent"),
    ("guestRecordingRelease", "guest_recording_release"),
)


class _VisibleTextParser(HTMLParser):
    """Identify visible text while decoding character references in sanitized HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_text = False

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.has_text = True


def _has_wording(choice: LegalChoice | None) -> bool:
    if choice is None or not choice.headline.strip():
        return False
    parser = _VisibleTextParser()
    parser.feed(choice.body_html)
    parser.close()
    return parser.has_text


def documentation_information(legal: LegalTexts | None, locale: str) -> LegalInformation | None:
    """Return the complete read-only documentation pair from one wording locale."""
    if legal is None:
        return None
    entry = legal_localization(legal, locale)
    if entry is None or not all(
        _has_wording(getattr(entry, field)) for _, field in _DOCUMENTATION_GROUPS
    ):
        entry = legal_localization(legal, legal.source_locale)
    if entry is None or not all(
        _has_wording(getattr(entry, field)) for _, field in _DOCUMENTATION_GROUPS
    ):
        return None
    return LegalInformation(
        locale=entry.locale,
        version=legal.version,
        sections=[
            LegalInformationSection(
                id=identifier,
                headline=getattr(entry, field).headline,
                body_html=getattr(entry, field).body_html,
            )
            for identifier, field in _DOCUMENTATION_GROUPS
        ],
    )
