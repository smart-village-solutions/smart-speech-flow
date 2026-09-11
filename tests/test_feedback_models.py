"""Validation bounds for the feedback submission contract.

The unusual one here is test_the_validation_error_never_echoes_the_text: it is
why the length check is a field_validator rather than Field(max_length=...).
Pydantic's built-in string_too_long error carries the offending input, which
would put feedback free text into a 422 response body.
"""

import pytest
from pydantic import ValidationError

from services.api_gateway.feedback.models import (
    MAX_IMPROVEMENTS_LENGTH,
    AnalyticsState,
    FeedbackSubmissionRequest,
)


def _valid(**overrides: object) -> dict:
    payload = {
        "session_id": "ABC12345",
        "translation_quality": 4,
        "performance": 5,
        "usability": 3,
        "net_promoter_score": 9,
        "improvements": "More languages please.",
        "form_version": "v1",
    }
    payload.update(overrides)
    return payload


def test_a_valid_submission_is_accepted() -> None:
    request = FeedbackSubmissionRequest(**_valid())

    assert request.translation_quality == 4
    assert request.net_promoter_score == 9


@pytest.mark.parametrize("field", ["translation_quality", "performance", "usability"])
@pytest.mark.parametrize("value", [0, 6, -1])
def test_ratings_outside_one_to_five_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmissionRequest(**_valid(**{field: value}))


@pytest.mark.parametrize("field", ["translation_quality", "performance", "usability"])
@pytest.mark.parametrize("value", [1, 5])
def test_rating_boundaries_are_accepted(field: str, value: int) -> None:
    assert FeedbackSubmissionRequest(**_valid(**{field: value}))


@pytest.mark.parametrize("value", [-1, 11])
def test_nps_outside_zero_to_ten_is_rejected(value: int) -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmissionRequest(**_valid(net_promoter_score=value))


@pytest.mark.parametrize("value", [0, 10])
def test_nps_boundaries_are_accepted(value: int) -> None:
    """Zero is a real score, not a missing one. An exclusive bound loses it."""
    assert FeedbackSubmissionRequest(**_valid(net_promoter_score=value))


def test_text_at_the_limit_is_accepted() -> None:
    request = FeedbackSubmissionRequest(**_valid(improvements="x" * MAX_IMPROVEMENTS_LENGTH))

    assert len(request.improvements) == MAX_IMPROVEMENTS_LENGTH


def test_the_model_deliberately_does_not_reject_long_text() -> None:
    """Length is a service-layer concern, and this is why.

    Pydantic attaches the offending value to every error it raises, and FastAPI
    copies errors() into the 422 body. A length constraint here -- built-in or
    hand-rolled -- would publish the free text on violation. FeedbackService
    enforces the limit instead; see test_feedback_service.py.
    """
    request = FeedbackSubmissionRequest(**_valid(improvements="x" * (MAX_IMPROVEMENTS_LENGTH + 1)))

    assert len(request.improvements) == MAX_IMPROVEMENTS_LENGTH + 1


def test_the_limit_counts_characters_not_bytes() -> None:
    """4000 emoji are 4000 characters; counting bytes would reject them."""
    request = FeedbackSubmissionRequest(**_valid(improvements="😀" * MAX_IMPROVEMENTS_LENGTH))

    assert len(request.improvements) == MAX_IMPROVEMENTS_LENGTH


def test_improvements_may_be_omitted() -> None:
    request = FeedbackSubmissionRequest(**_valid(improvements=None))

    assert request.improvements is None


def test_a_missing_session_is_allowed() -> None:
    """The admin dashboard offers feedback outside any session (spec O1)."""
    request = FeedbackSubmissionRequest(**_valid(session_id=None))

    assert request.session_id is None


def test_form_version_defaults_to_the_current_one() -> None:
    payload = _valid()
    del payload["form_version"]

    assert FeedbackSubmissionRequest(**payload).form_version == "v1"


def test_unknown_fields_are_rejected() -> None:
    """A client must not be able to smuggle in a tenant or a feedback id."""
    with pytest.raises(ValidationError):
        FeedbackSubmissionRequest(**_valid(tenant_id="attacker-chosen"))


def test_a_client_supplied_session_ref_is_rejected() -> None:
    """Analytical identifiers are server-owned; see tenant_context.py."""
    with pytest.raises(ValidationError):
        FeedbackSubmissionRequest(**_valid(session_ref="f" * 32))


@pytest.mark.parametrize(
    "invalid",
    [
        {"translation_quality": 9},
        {"performance": 0},
        {"usability": -1},
        {"net_promoter_score": 11},
        {"form_version": "v" * 64},
        {"tenant_id": "attacker-chosen"},
        {"session_id": "s" * 200},
    ],
    ids=[
        "bad-quality",
        "bad-performance",
        "bad-usability",
        "bad-nps",
        "long-form-version",
        "extra-field",
        "long-session-id",
    ],
)
def test_no_validation_error_ever_echoes_the_free_text(invalid: dict) -> None:
    """The invariant: a 422 must never publish what the user typed.

    FastAPI copies ValidationError.errors() -- including each error's `input`
    -- into the response body. Whatever else is wrong with a submission, the
    improvement text must not come back out with the complaint.
    """
    secret = "SENTINEL-PURPLE-RHINOCEROS"
    payload = _valid(improvements=f"The translator said {secret}.", **invalid)

    with pytest.raises(ValidationError) as caught:
        FeedbackSubmissionRequest(**payload)

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value.errors())


def test_the_analytics_states_are_the_three_the_schema_allows() -> None:
    """The CHECK constraint in 001_feedback.sql lists exactly these."""
    assert {state.value for state in AnalyticsState} == {
        "pending",
        "delivered",
        "not_applicable",
    }
