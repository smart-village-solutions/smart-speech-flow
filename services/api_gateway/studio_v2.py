"""Studio contract v2: a strict storage policy and lenient content.

The policy decides persistence and consent, so any error in it fails the read.
Content only replaces bundled copy, so an invalid section is logged and dropped
on its own, and the browser falls back for that section alone.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    model_validator,
)

from .studio_v1 import is_safe_https_url

logger = logging.getLogger(__name__)

CONTRACT_VERSION_PATTERN = r"^2[.](0|[1-9][0-9]*)$"
REVISION_PATTERN = r"^sha256:[0-9a-f]{64}$"
LOCALE_PATTERN = r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$"
QUESTION_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9]*$"


def _https_url(value: str) -> str:
    if len(value) > 2048 or not is_safe_https_url(value):
        raise ValueError("URL must be an absolute HTTPS URL")
    return value


def _known_time_zone(value: str) -> str:
    # Only zones this gateway knows reach the browser; Debian 13 images lack the
    # legacy aliases (Europe/Kiev), so an alias falls back to the browser's zone.
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timeZone must be an IANA time zone") from error
    return value


def _log_dropped(section: str, error: ValidationError) -> None:
    # Locations only: str(error) would copy Studio content into the log.
    locations = ", ".join(
        ".".join(str(part) for part in detail["loc"]) or "<root>"
        for detail in error.errors(include_url=False, include_input=False)
    )
    logger.warning("Studio content dropped: %s (invalid at %s)", section, locations)


def _none_when_invalid(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> Any:
    try:
        return handler(value)
    except ValidationError as error:
        section = (info.context or {}).get("section", "content")
        _log_dropped(f"{section}.{info.field_name}", error)
        return None


def _validate_or_none[M: BaseModel](model: type[M], raw: object, section: str) -> M | None:
    try:
        return model.model_validate(raw, context={"section": section})
    except ValidationError as error:
        _log_dropped(section, error)
        return None


Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Html = Annotated[str, StringConstraints(min_length=1, max_length=65_536)]
Locale = Annotated[str, StringConstraints(max_length=35, pattern=LOCALE_PATTERN)]
HttpsUrl = Annotated[str, AfterValidator(_https_url)]
TimeZone = Annotated[
    str, StringConstraints(min_length=1, max_length=100), AfterValidator(_known_time_zone)
]


class StudioContractError(ValueError):
    """A v2 body SSF must not use; `reason` completes the client's error code."""

    def __init__(self, reason: Literal["response_invalid", "tenant_mismatch"]) -> None:
        super().__init__(reason)
        self.reason = reason


class _StudioModel(BaseModel):
    # Unknown fields are ignored: a 2.x minor version only adds optional ones.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)


class Media(_StudioModel):
    url: HttpsUrl
    alternative_text: str = Field(alias="alternativeText", max_length=500)


LenientMedia = Annotated[Media | None, WrapValidator(_none_when_invalid)]


class Branding(_StudioModel):
    logo: LenientMedia = None
    icon: LenientMedia = None


class _Question(_StudioModel):
    id: str = Field(max_length=64, pattern=QUESTION_ID_PATTERN)
    headline: Text | None = None
    question: Text
    required: bool = False


class _RangeQuestion(_Question):
    min: int
    max: int

    @model_validator(mode="after")
    def _min_below_max(self) -> Self:
        if self.min >= self.max:
            raise ValueError("min must be less than max")
        return self


class RatingQuestion(_RangeQuestion):
    type: Literal["rating"]
    # Zero stars cannot be told apart from no answer.
    min: int = Field(ge=1, le=9)
    max: int = Field(ge=1, le=10)


class ScaleQuestion(_RangeQuestion):
    type: Literal["scale"]
    min: int = Field(ge=0, le=9)
    max: int = Field(ge=1, le=10)
    min_label: Text | None = Field(default=None, alias="minLabel")
    max_label: Text | None = Field(default=None, alias="maxLabel")


class LongTextQuestion(_Question):
    type: Literal["longText"]
    placeholder: Text | None = None
    max_length: int = Field(default=4000, alias="maxLength", ge=1, le=4000)


FeedbackQuestion = Annotated[
    RatingQuestion | ScaleQuestion | LongTextQuestion, Field(discriminator="type")
]


class FeedbackForm(_StudioModel):
    headline: Text
    questions: tuple[FeedbackQuestion, ...] = Field(min_length=1, max_length=20, strict=False)
    notice_html: Html = Field(alias="noticeHtml")
    button: Text

    @model_validator(mode="after")
    def _unique_question_ids(self) -> Self:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


LenientFeedbackForm = Annotated[FeedbackForm | None, WrapValidator(_none_when_invalid)]


class LoadLabels(_StudioModel):
    headline: Text
    green: Text
    yellow: Text
    red: Text


class DashboardTexts(_StudioModel):
    headline: Text
    explanation_html: Html = Field(alias="explanationHtml")
    call_to_action: Text = Field(alias="callToAction")
    load: LoadLabels


class NewConversationTexts(_StudioModel):
    headline: Text
    description_html: Html = Field(alias="descriptionHtml")


class StaffContent(_StudioModel):
    locale: Locale
    dashboard: DashboardTexts
    new_conversation: NewConversationTexts = Field(alias="newConversation")
    feedback: LenientFeedbackForm = None


class GuestLanguageContent(_StudioModel):
    locale: Locale
    native_name: Text = Field(alias="nativeName")
    staff_name: Text = Field(alias="staffName")
    icon: LenientMedia = None
    explanation_html: Html = Field(alias="explanationHtml")
    storage_question_html: Html | None = Field(alias="storageQuestionHtml")
    # Not lenient: the spec drops the whole language for an invalid form.
    feedback: FeedbackForm | None = None

    @model_validator(mode="before")
    @classmethod
    def _lift_guest_texts(cls, data: Any) -> Any:
        return _lift(data, "guest", ("explanationHtml", "storageQuestionHtml"))


class LegalLinks(_StudioModel):
    imprint_url: HttpsUrl = Field(alias="imprintUrl")
    privacy_policy_url: HttpsUrl = Field(alias="privacyPolicyUrl")
    accessibility_statement_url: HttpsUrl | None = Field(alias="accessibilityStatementUrl")


class StartpageTexts(_StudioModel):
    enter_code: Text = Field(alias="enterCode")
    send: Text
    login: Text


class LoginTexts(_StudioModel):
    headline: Text
    description_html: Html = Field(alias="descriptionHtml")


class InstallationContent(_StudioModel):
    configuration_revision: str = Field(alias="configurationRevision", pattern=REVISION_PATTERN)
    branding: Branding
    legal: LegalLinks
    locale: Locale
    startpage: StartpageTexts
    login: LoginTexts
    feedback: LenientFeedbackForm = None

    @model_validator(mode="before")
    @classmethod
    def _lift_localization(cls, data: Any) -> Any:
        lifted = _lift(data, "localization", ("locale", "startpage", "login", "feedback"))
        if isinstance(lifted, dict):
            lifted["branding"] = _branding_body(lifted.get("branding"))
        return lifted


class RuntimePolicy(_StudioModel):
    contract_version: str
    configuration_revision: str
    tenant_id: str
    mode: Literal["ask", "disabled"]
    retention_hours: int | None


class RuntimeContent(_StudioModel):
    # Display-only and lenient: neither may refuse persistence.
    display_name: str | None
    time_zone: str | None
    branding: Branding
    staff: StaffContent | None
    guest_languages: tuple[GuestLanguageContent, ...]


class RuntimeRead(_StudioModel):
    policy: RuntimePolicy
    content: RuntimeContent


class _Versioned(_StudioModel):
    contract_version: str = Field(alias="contractVersion", pattern=CONTRACT_VERSION_PATTERN)


class _TenantId(_StudioModel):
    id: str = Field(min_length=1, max_length=128)


class _TenantTexts(_StudioModel):
    display_name: Annotated[
        Annotated[str, StringConstraints(min_length=1, max_length=200)] | None,
        WrapValidator(_none_when_invalid),
    ] = Field(default=None, alias="displayName")
    time_zone: Annotated[TimeZone | None, WrapValidator(_none_when_invalid)] = Field(
        default=None, alias="timeZone"
    )


class _Storage(_StudioModel):
    mode: Literal["ask", "disabled"]
    retention_hours: int | None = Field(alias="retentionHours", ge=0, le=8760)

    @model_validator(mode="after")
    def _retention_matches_mode(self) -> Self:
        if (self.mode == "ask") != (self.retention_hours is not None):
            raise ValueError("retentionHours is an integer for ask and null for disabled")
        return self


class _PolicyView(_Versioned):
    configuration_revision: str = Field(alias="configurationRevision", pattern=REVISION_PATTERN)
    tenant: _TenantId
    conversation_content_storage: _Storage = Field(alias="conversationContentStorage")


def _lift(data: Any, block: str, keys: tuple[str, ...]) -> Any:
    """Move `keys` up from the nested `block`; same-named keys outside it never count."""
    if not isinstance(data, Mapping):
        return data
    lifted = {key: value for key, value in data.items() if key != block and key not in keys}
    nested = data.get(block)
    if isinstance(nested, Mapping):
        lifted.update({key: nested[key] for key in keys if key in nested})
    return lifted


def _branding_body(raw: object) -> object:
    if isinstance(raw, Mapping):
        return raw
    logger.warning("Studio content dropped: branding (not an object)")
    return {}


def _guest_languages(raw: object, mode: str) -> tuple[GuestLanguageContent, ...]:
    if not isinstance(raw, list):
        logger.warning("Studio content dropped: guestLanguages (not a list)")
        return ()
    languages = []
    for index, item in enumerate(raw):
        section = f"guestLanguages.{index}"
        language = _validate_or_none(GuestLanguageContent, item, section)
        if language is None:
            continue
        if (language.storage_question_html is None) != (mode == "disabled"):
            logger.warning(
                "Studio content dropped: %s (storage question contradicts the mode)", section
            )
            continue
        languages.append(language)
    return tuple(languages)


def parse_runtime_configuration_v2(body: object, *, expected_tenant_id: str) -> RuntimeRead:
    """Validate the policy strictly and keep every content section that is valid.

    Raises:
        StudioContractError: the policy is invalid or names another tenant.
    """
    if not isinstance(body, Mapping):
        raise StudioContractError("response_invalid")
    try:
        view = _PolicyView.model_validate(dict(body))
    except ValidationError:
        raise StudioContractError("response_invalid") from None
    # Studio's tenant id is not guaranteed ASCII, and compare_digest raises on non-ASCII str.
    if not hmac.compare_digest(view.tenant.id.encode(), expected_tenant_id.encode()):
        raise StudioContractError("tenant_mismatch")
    storage = view.conversation_content_storage
    tenant = _TenantTexts.model_validate(body["tenant"], context={"section": "tenant"})
    branding = Branding.model_validate(
        _branding_body(body.get("branding")), context={"section": "branding"}
    )
    return RuntimeRead(
        policy=RuntimePolicy(
            contract_version=view.contract_version,
            configuration_revision=view.configuration_revision,
            tenant_id=view.tenant.id,
            mode=storage.mode,
            retention_hours=storage.retention_hours,
        ),
        content=RuntimeContent(
            display_name=tenant.display_name,
            time_zone=tenant.time_zone,
            branding=branding,
            staff=_validate_or_none(StaffContent, body.get("staff"), "staff"),
            guest_languages=_guest_languages(body.get("guestLanguages"), storage.mode),
        ),
    )


def parse_installation_content_v2(body: object) -> InstallationContent:
    """Validate installation content; only branding media and the form are lenient.

    Raises:
        StudioContractError: the version, revision, legal links or texts are invalid.
    """
    if not isinstance(body, Mapping):
        raise StudioContractError("response_invalid")
    try:
        _Versioned.model_validate(dict(body))
        return InstallationContent.model_validate(dict(body), context={"section": "installation"})
    except ValidationError:
        raise StudioContractError("response_invalid") from None
