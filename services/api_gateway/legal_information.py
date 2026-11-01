"""Read-only legal wording: content only, never a consent or recording capability."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .studio_legal import LegalTexts, legal_localization


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
