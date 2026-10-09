"""The feedback submission contract and its stored form."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Discriminator, Field, SkipValidation, Tag

MAX_IMPROVEMENTS_LENGTH: Final[int] = 4000
CURRENT_FORM_VERSION: Final[str] = "v1"
# Stored as form_version for v2 bodies; form_source and the snapshot say the rest.
V2_FORM_VERSION: Final[str] = "v2"
RETENTION_POLICY_VERSION: Final[str] = "v1-12-months"


class AnalyticsState(str, Enum):
    """Whether the structured half of a submission reached the pipeline.

    NOT_APPLICABLE exists so a deployment with telemetry switched off does not
    accumulate a reconciliation backlog that nothing will ever drain. The three
    values are mirrored by the CHECK constraint in 001_feedback.sql; adding one
    here without a migration makes every insert of it fail.
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    NOT_APPLICABLE = "not_applicable"


class FeedbackTextTooLong(ValueError):
    """The improvement text exceeded MAX_IMPROVEMENTS_LENGTH.

    Deliberately carries no copy of the offending text: it is raised so a
    handler can answer 422 without the value reaching the response.
    """


class FeedbackSubmissionRequest(BaseModel):
    """What the browser may send. Everything analytical is server-owned.

    `improvements` carries NO validation constraint, and that is deliberate.
    Pydantic attaches the offending value to every error it raises -- `input`
    in `errors()`, and a truncated fragment in `str(...)` -- and FastAPI copies
    `errors()` straight into the 422 response body. Any constraint here,
    built-in or hand-rolled, therefore publishes the free text on violation.
    Length is enforced in FeedbackService instead, where the error we raise is
    the error the caller sees.
    """

    # forbid, not ignore: a client-supplied tenant_id, feedback_id or
    # session_ref is a trust-boundary probe and should fail loudly rather than
    # be silently dropped.
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, max_length=128)
    translation_quality: int = Field(ge=1, le=5)
    performance: int = Field(ge=1, le=5)
    usability: int = Field(ge=1, le=5)
    net_promoter_score: int = Field(ge=0, le=10)
    improvements: str | None = None
    form_version: str = Field(default=CURRENT_FORM_VERSION, max_length=32)


Audience = Literal["guest", "staff", "installation"]
FormSource = Literal["studio", "bundled"]


class FeedbackSubmissionV2(BaseModel):
    """Answers by question id, for the form the browser rendered.

    `answers` is deliberately not validated here, for the reason the v1 model
    gives about `improvements`, and more: an error inside a mapping carries the
    key in `loc` as well as the value in `input`. SkipValidation keeps the
    declared shape in the OpenAPI document while FeedbackService does the
    checking, against the form, with errors that carry neither.
    """

    model_config = ConfigDict(extra="forbid")

    audience: Audience
    session_id: str | None = Field(default=None, max_length=128)
    locale: str = Field(min_length=2, max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
    form_source: FormSource
    configuration_revision: str | None = Field(default=None, max_length=128)
    answers: SkipValidation[dict[str, int | str | None]]


def _body_version(body: Any) -> str:
    """v2 when the body names an audience. Chosen by presence, never by trying both."""
    if isinstance(body, dict):
        return "v2" if "audience" in body else "v1"
    return "v2" if isinstance(body, FeedbackSubmissionV2) else "v1"


FeedbackSubmission = Annotated[
    Annotated[FeedbackSubmissionV2, Tag("v2")] | Annotated[FeedbackSubmissionRequest, Tag("v1")],
    Discriminator(_body_version),
]


class FeedbackAcceptedResponse(BaseModel):
    """The opaque confirmation identifier."""

    feedback_id: UUID


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    """One authoritative row. `text_answers_ciphertext` is never plaintext.

    `text_answers_legacy` marks a row converted by migration 004, whose
    envelope holds the v1 improvement text rather than a JSON object.
    """

    feedback_id: UUID
    tenant_id: str
    session_ref: str
    audience: Audience
    form_source: FormSource
    configuration_revision: str | None
    form_locale: str | None
    form_snapshot: tuple[dict[str, Any], ...]
    numeric_answers: dict[str, int]
    text_answers_ciphertext: bytes | None
    text_answers_legacy: bool
    form_version: str
    retention_policy_version: str
    consent_snapshot: dict[str, Any]
    analytics_event_id: UUID
    analytics_state: AnalyticsState
    created_at: datetime
    expires_at: datetime
