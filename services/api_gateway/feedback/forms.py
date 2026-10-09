"""The form a feedback submission is checked against.

The bundled form needs nothing. A Studio form is the one of the submitted
revision while the content cache still holds it, and otherwise the latest the
content service can give, live or stale. Installation content keeps a single
revision, so installation feedback is always checked against the current one.
When no form can be obtained at all, the submission is refused as retryable
rather than accepted unchecked.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..studio_content import TenantContent
from ..studio_content_service import ContentUnavailable, StudioContentService
from ..studio_locales import ssf_language
from ..studio_v2 import FeedbackForm
from .answers import FeedbackFormChanged, FormRules, rules_from_studio
from .bundled_form import bundled_rules
from .models import Audience, FormSource


class FeedbackFormUnavailable(RuntimeError):
    """Studio cannot be read and no content was read before; retryable."""


@dataclass(frozen=True, slots=True)
class ResolvedForm:
    rules: FormRules
    # The revision whose form the answers are checked against; None when bundled.
    revision: str | None


class FeedbackForms:
    def __init__(self, content: StudioContentService) -> None:
        self._content = content

    async def resolve(
        self,
        *,
        audience: Audience,
        source: FormSource,
        tenant_id: str,
        revision: str | None,
        locale: str,
        correlation_id: str,
    ) -> ResolvedForm:
        if source == "bundled":
            return ResolvedForm(bundled_rules(), None)
        if audience == "installation":
            return await self._installation(correlation_id)
        content = await self._tenant_content(tenant_id, revision, correlation_id)
        form = _staff_form(content) if audience == "staff" else _guest_form(content, locale)
        return _resolved(form, content.revision)

    async def _installation(self, correlation_id: str) -> ResolvedForm:
        try:
            content = await self._content.installation_content(correlation_id)
        except ContentUnavailable:
            raise FeedbackFormUnavailable("installation content is unavailable") from None
        return _resolved(content.feedback, content.configuration_revision)

    async def _tenant_content(
        self, tenant_id: str, revision: str | None, correlation_id: str
    ) -> TenantContent:
        held = (
            self._content.tenant_content_at(tenant_id, revision, endpoint="feedback")
            if revision
            else None
        )
        if held is not None:
            return held
        try:
            return await self._content.tenant_content(
                tenant_id, correlation_id, endpoint="feedback"
            )
        except ContentUnavailable:
            raise FeedbackFormUnavailable("tenant content is unavailable") from None


def _resolved(form: FeedbackForm | None, revision: str) -> ResolvedForm:
    if form is None:
        raise FeedbackFormChanged("form_missing")
    return ResolvedForm(rules_from_studio(form), revision)


def _staff_form(content: TenantContent) -> FeedbackForm | None:
    return content.staff.feedback if content.staff is not None else None


def _guest_form(content: TenantContent, locale: str) -> FeedbackForm | None:
    code = ssf_language(locale)
    language = content.guest_languages.get(code) if code is not None else None
    return language.feedback if language is not None else None
