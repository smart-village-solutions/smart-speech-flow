"""Optional Studio legal wording, independent from recording authorization."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from .studio_html import safe_html

Text = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
Locale = Annotated[
    str, StringConstraints(max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
]


class _LegalModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, strict=True)


class LegalChoice(_LegalModel):
    headline: Text
    body_html: Annotated[str, StringConstraints(min_length=1, max_length=65_536)]
    accept_label: Text
    decline_label: Text

    @field_validator("body_html")
    @classmethod
    def _sanitize(cls, value: str) -> str:
        return safe_html(value)


class RecordingStatusTexts(_LegalModel):
    waiting: Text
    running: Text
    stopped: Text
    renewed_release_required: Text


class LocalizedRecordingStatus(RecordingStatusTexts):
    locale: Locale


class LegalLocalization(_LegalModel):
    locale: Locale
    mode2_consent: LegalChoice | None = None
    mode3_consent: LegalChoice | None = None
    guest_recording_release: LegalChoice | None = None
    staff_recording_release: LegalChoice | None = None
    recording_status: RecordingStatusTexts | None = None


class LegalTexts(_LegalModel):
    source_locale: Locale
    version: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    localizations: tuple[LegalLocalization, ...] = Field(min_length=1, max_length=40, strict=False)

    @model_validator(mode="after")
    def _locales(self) -> Self:
        locales = [entry.locale.casefold() for entry in self.localizations]
        if len(set(locales)) != len(locales) or self.source_locale.casefold() not in locales:
            raise ValueError("Legal locales must be unique and include the source")
        return self


def legal_localization(legal: LegalTexts | None, locale: str) -> LegalLocalization | None:
    """Prefer the requested language, otherwise identify the actual source locale."""
    if legal is None:
        return None
    normalized = locale.casefold()
    for entry in legal.localizations:
        if entry.locale.casefold() == normalized:
            return entry
    language = normalized.split("-", 1)[0]
    for entry in legal.localizations:
        if entry.locale.casefold().split("-", 1)[0] == language:
            return entry
    return next(
        entry
        for entry in legal.localizations
        if entry.locale.casefold() == legal.source_locale.casefold()
    )


def recording_status(legal: LegalTexts | None, locale: str) -> LocalizedRecordingStatus | None:
    entry = legal_localization(legal, locale)
    if entry is None or entry.recording_status is None:
        return None
    return LocalizedRecordingStatus(locale=entry.locale, **entry.recording_status.model_dump())
