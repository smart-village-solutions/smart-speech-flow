"""Studio display content, sanitised once and kept by revision.

The storage mode is not held here and cannot be: it decides persistence and
consent, so every use reads it live. Nor is the tenant display name, which SSF
never shows. `TenantContent` has slots and no field for either.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .studio_html import safe_html
from .studio_locales import GUEST_LANGUAGES, SkipReason, guest_languages_by_code
from .studio_runtime_flow import RuntimeConfigurationFetcher
from .studio_v2 import (
    Branding,
    FeedbackForm,
    GuestLanguageContent,
    InstallationContent,
    RuntimeRead,
    StaffContent,
)

logger = logging.getLogger(__name__)

# Enough for a feedback submission made against a form that changed meanwhile.
MAX_REVISIONS_PER_TENANT = 4


@dataclass(frozen=True, slots=True)
class TenantContent:
    """One revision of a tenant's display content."""

    revision: str
    time_zone: str | None
    branding: Branding
    staff: StaffContent | None
    # Keyed by SSF language code, in SSF's order.
    guest_languages: Mapping[str, GuestLanguageContent]


@dataclass(frozen=True, slots=True)
class Cached[T]:
    content: T
    age_seconds: float


def _form(form: FeedbackForm | None) -> FeedbackForm | None:
    if form is None:
        return None
    return form.model_copy(update={"notice_html": safe_html(form.notice_html)})


def _staff(staff: StaffContent | None) -> StaffContent | None:
    if staff is None:
        return None
    dashboard = staff.dashboard
    new_conversation = staff.new_conversation
    return staff.model_copy(
        update={
            "dashboard": dashboard.model_copy(
                update={"explanation_html": safe_html(dashboard.explanation_html)}
            ),
            "new_conversation": new_conversation.model_copy(
                update={"description_html": safe_html(new_conversation.description_html)}
            ),
            "feedback": _form(staff.feedback),
        }
    )


def _guest(language: GuestLanguageContent) -> GuestLanguageContent:
    question = language.storage_question_html
    return language.model_copy(
        update={
            "explanation_html": safe_html(language.explanation_html),
            "storage_question_html": None if question is None else safe_html(question),
            "feedback": _form(language.feedback),
        }
    )


def sanitised_installation(content: InstallationContent) -> InstallationContent:
    login = content.login
    return content.model_copy(
        update={
            "login": login.model_copy(
                update={"description_html": safe_html(login.description_html)}
            ),
            "feedback": _form(content.feedback),
        }
    )


def _tenant_content(read: RuntimeRead, on_skip: Callable[[SkipReason], None]) -> TenantContent:
    content = read.content
    skipped: list[SkipReason] = []
    mapped = guest_languages_by_code(content.guest_languages, skipped.append)
    built = TenantContent(
        revision=read.policy.configuration_revision,
        time_zone=content.time_zone,
        branding=content.branding,
        staff=_staff(content.staff),
        guest_languages=MappingProxyType(
            {code: _guest(mapped[code]) for code in GUEST_LANGUAGES if code in mapped}
        ),
    )
    # Reported once the revision is held, so a failed insert retried later counts once.
    for reason in skipped:
        on_skip(reason)
    return built


def _ignore_skip(reason: SkipReason) -> None:
    del reason


@dataclass(frozen=True, slots=True)
class _Latest:
    revision: str
    fetched_at: float


class StudioContentCache:
    """Each tenant's recent revisions and a pointer to its latest; one installation entry."""

    def __init__(
        self,
        *,
        on_skip: Callable[[SkipReason], None] = _ignore_skip,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_skip = on_skip
        self._clock = clock
        self._revisions: dict[str, OrderedDict[str, TenantContent]] = {}
        self._latest: dict[str, _Latest] = {}
        self._installation: InstallationContent | None = None
        self._installation_fetched_at = 0.0

    def record(self, read: RuntimeRead) -> TenantContent:
        """Keep a live read's content; a revision already held is not sanitised again."""
        tenant_id = read.policy.tenant_id
        revision = read.policy.configuration_revision
        revisions = self._revisions.setdefault(tenant_id, OrderedDict())
        content = revisions.get(revision)
        if content is None:
            content = _tenant_content(read, self._on_skip)
            revisions[revision] = content
        revisions.move_to_end(revision)
        while len(revisions) > MAX_REVISIONS_PER_TENANT:
            revisions.popitem(last=False)
        self._latest[tenant_id] = _Latest(revision, self._clock())
        return content

    def try_record(self, read: RuntimeRead) -> TenantContent | None:
        """`record`, but a failure to cache is logged and answered with None.

        Display content must never cost a policy read, and a read that was
        taken but could not be cached must reach a content route as a Studio
        failure (stale or bundled), never as a 500.
        """
        try:
            return self.record(read)
        except Exception as error:  # fallback: content falls back, the read stands
            # The type alone: a message could carry Studio content into the log.
            logger.warning("Studio content not cached (%s)", type(error).__name__)
            return None

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    def latest(self, tenant_id: str) -> Cached[TenantContent] | None:
        latest = self._latest.get(tenant_id)
        if latest is None:
            return None
        content = self._revisions[tenant_id][latest.revision]
        return Cached(content, self._clock() - latest.fetched_at)

    def at_revision(self, tenant_id: str, revision: str) -> TenantContent | None:
        """A recent revision's content, to check a submission against the form it answered."""
        return self._revisions.get(tenant_id, OrderedDict()).get(revision)

    def record_installation(self, content: InstallationContent) -> InstallationContent:
        current = self._installation
        if current is None or current.configuration_revision != content.configuration_revision:
            current = sanitised_installation(content)
            self._installation = current
        self._installation_fetched_at = self._clock()
        return current

    def installation(self) -> Cached[InstallationContent] | None:
        if self._installation is None:
            return None
        return Cached(self._installation, self._clock() - self._installation_fetched_at)


class ContentRecordingFetcher:
    """Pass every live runtime read on unchanged, refreshing the content cache from it.

    Session create, activation and the persistence gate all read through this,
    so display content follows each policy read without another Studio request.
    """

    def __init__(self, inner: RuntimeConfigurationFetcher, cache: StudioContentCache) -> None:
        self._inner = inner
        self._cache = cache

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        read = await self._inner.fetch(tenant_id, correlation_id)
        self._cache.try_record(read)
        return read
