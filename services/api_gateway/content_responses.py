"""The JSON the browser content routes answer with.

camelCase like `/api/login/tenants`. The models list their fields, so nothing
else Studio sends, the tenant display name included, can reach a browser.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .message_models import SUPPORTED_LANGUAGES
from .studio_content import TenantContent
from .studio_content_service import GuestContent
from .studio_locales import GUEST_LANGUAGES
from .studio_v2 import FeedbackForm, InstallationContent, Media


class _Body(BaseModel):
    # Every field is always sent, so the schema marks defaulted ones required too.
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )


class ContentMedia(_Body):
    url: str
    alternative_text: str


class ContentBranding(_Body):
    logo: ContentMedia | None
    icon: ContentMedia | None


class _ContentQuestion(_Body):
    id: str
    headline: str | None
    question: str
    required: bool


class ContentRatingQuestion(_ContentQuestion):
    type: Literal["rating"]
    min: int
    max: int


class ContentScaleQuestion(_ContentQuestion):
    type: Literal["scale"]
    min: int
    max: int
    min_label: str | None
    max_label: str | None


class ContentLongTextQuestion(_ContentQuestion):
    type: Literal["longText"]
    placeholder: str | None
    max_length: int


class ContentFeedbackForm(_Body):
    headline: str
    questions: list[
        Annotated[
            ContentRatingQuestion | ContentScaleQuestion | ContentLongTextQuestion,
            Field(discriminator="type"),
        ]
    ]
    notice_html: str
    button: str


class ContentLegal(_Body):
    imprint_url: str
    privacy_policy_url: str
    accessibility_statement_url: str | None


class ContentStartpage(_Body):
    enter_code: str
    send: str
    login: str


class ContentLogin(_Body):
    headline: str
    description_html: str


class InstallationContentResponse(_Body):
    revision: str
    branding: ContentBranding
    legal: ContentLegal
    locale: str
    startpage: ContentStartpage
    login: ContentLogin
    feedback: ContentFeedbackForm | None


class BundledGuestLanguage(_Body):
    code: str
    name: str
    native: str
    provided: Literal[False] = False


class ProvidedGuestLanguage(_Body):
    code: str
    name: str
    native: str
    provided: Literal[True] = True
    native_name: str
    icon: ContentMedia | None


class GuestLanguagesResponse(_Body):
    languages: list[
        Annotated[ProvidedGuestLanguage | BundledGuestLanguage, Field(discriminator="provided")]
    ]


class ContentStorage(_Body):
    mode: Literal["ask", "disabled", "unknown"]


class ProvidedGuestContent(_Body):
    storage: ContentStorage
    provided: Literal[True] = True
    revision: str
    explanation_html: str
    storage_question_html: str | None
    feedback: ContentFeedbackForm | None


class UnprovidedGuestContent(_Body):
    storage: ContentStorage
    provided: Literal[False] = False


GuestContentResponse = Annotated[
    ProvidedGuestContent | UnprovidedGuestContent, Field(discriminator="provided")
]


class ContentLoadLabels(_Body):
    headline: str
    green: str
    yellow: str
    red: str


class ContentDashboard(_Body):
    headline: str
    explanation_html: str
    call_to_action: str
    load: ContentLoadLabels


class ContentNewConversation(_Body):
    headline: str
    description_html: str


class ContentStaff(_Body):
    locale: str
    dashboard: ContentDashboard
    new_conversation: ContentNewConversation
    feedback: ContentFeedbackForm | None


class StaffContentResponse(_Body):
    revision: str
    time_zone: str | None
    branding: ContentBranding
    staff: ContentStaff | None
    # SSF language code to its name in the staff language.
    guest_language_names: dict[str, str]


def _media(media: Media | None) -> ContentMedia | None:
    return None if media is None else ContentMedia.model_validate(media.model_dump())


def _form(form: FeedbackForm | None) -> ContentFeedbackForm | None:
    return None if form is None else ContentFeedbackForm.model_validate(form.model_dump())


def installation_response(content: InstallationContent) -> InstallationContentResponse:
    body = content.model_dump(exclude={"configuration_revision"})
    return InstallationContentResponse.model_validate(
        {**body, "revision": content.configuration_revision}
    )


def guest_languages_response(content: TenantContent | None) -> GuestLanguagesResponse:
    """SSF's guest languages; those Studio provides carry its native name and icon."""
    provided = content.guest_languages if content is not None else {}
    languages: list[ProvidedGuestLanguage | BundledGuestLanguage] = []
    for code in GUEST_LANGUAGES:
        names = SUPPORTED_LANGUAGES[code]
        studio = provided.get(code)
        if studio is None:
            languages.append(
                BundledGuestLanguage(code=code, name=names["name"], native=names["native"])
            )
        else:
            languages.append(
                ProvidedGuestLanguage(
                    code=code,
                    name=names["name"],
                    native=names["native"],
                    native_name=studio.native_name,
                    icon=_media(studio.icon),
                )
            )
    return GuestLanguagesResponse(languages=languages)


def guest_content_response(
    guest: GuestContent, language: str
) -> ProvidedGuestContent | UnprovidedGuestContent:
    storage = ContentStorage(mode=guest.mode)
    content = guest.content
    studio = content.guest_languages.get(language) if content is not None else None
    if content is None or studio is None:
        return UnprovidedGuestContent(storage=storage)
    return ProvidedGuestContent(
        storage=storage,
        revision=content.revision,
        explanation_html=studio.explanation_html,
        storage_question_html=studio.storage_question_html,
        feedback=_form(studio.feedback),
    )


def staff_content_response(content: TenantContent) -> StaffContentResponse:
    staff = content.staff
    return StaffContentResponse(
        revision=content.revision,
        time_zone=content.time_zone,
        branding=ContentBranding.model_validate(content.branding.model_dump()),
        staff=None if staff is None else ContentStaff.model_validate(staff.model_dump()),
        guest_language_names={
            code: language.staff_name for code, language in content.guest_languages.items()
        },
    )
