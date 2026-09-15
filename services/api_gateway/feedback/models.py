"""The feedback submission contract and its stored form."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_IMPROVEMENTS_LENGTH: Final[int] = 4000
CURRENT_FORM_VERSION: Final[str] = "v1"
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


class FeedbackAcceptedResponse(BaseModel):
    """The opaque confirmation identifier."""

    feedback_id: UUID


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    """One authoritative row. `improvements_ciphertext` is never plaintext."""

    feedback_id: UUID
    tenant_id: str
    session_ref: str
    translation_quality: int
    performance: int
    usability: int
    net_promoter_score: int
    improvements_ciphertext: bytes | None
    form_version: str
    retention_policy_version: str
    consent_snapshot: dict[str, Any]
    analytics_event_id: UUID
    analytics_state: AnalyticsState
    created_at: datetime
    expires_at: datetime
