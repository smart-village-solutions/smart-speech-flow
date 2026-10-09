"""Which form a submission is checked against: its revision when held, else the latest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.feedback.answers import FeedbackFormChanged, validate_answers
from services.api_gateway.feedback.bundled_form import bundled_rules
from services.api_gateway.feedback.forms import FeedbackForms, FeedbackFormUnavailable
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_content_metrics import StudioContentMetrics
from services.api_gateway.studio_content_service import StudioContentService
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from services.api_gateway.studio_v2 import (
    parse_installation_content_v2,
    parse_runtime_configuration_v2,
)

# Captured from production Studio: Kassel's forms ask the five bundled questions.
FIXTURES = Path(__file__).parent / "fixtures" / "studio_v2"
TENANT = "tenant-kassel"
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64
DOWN = StudioRuntimeV2ClientError("studio_runtime_network_error", retryable=True)
BUNDLED_ANSWERS = {
    "translationQuality": 4,
    "performance": 5,
    "usability": 3,
    "recommendation": 9,
    "improvementIdeas": "ok",
}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Studio:
    """Answers with the next scripted outcome, then the last one forever."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def fetch(self, *arguments):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _body(revision: str) -> dict:
    body = _fixture("runtime-tenant-kassel.json")
    body["configurationRevision"] = revision
    return body


def _read(body: dict):
    return parse_runtime_configuration_v2(body, expected_tenant_id=TENANT)


def _without_usability(revision: str) -> dict:
    """A newer revision whose forms no longer ask about usability."""
    body = _body(revision)
    for owner in (body["staff"], *body["guestLanguages"]):
        owner["feedback"]["questions"] = [
            question
            for question in owner["feedback"]["questions"]
            if question["id"] != "usability"
        ]
    return body


def _installation(with_form: bool = True, revision: str = NEW) -> object:
    body = _fixture("installation.json")
    body["configurationRevision"] = revision
    if not with_form:
        del body["localization"]["feedback"]
    return parse_installation_content_v2(body)


def _forms(runtime=None, installation=None, clock=None):
    clock = clock or Clock()
    cache = StudioContentCache(clock=clock)
    registry = CollectorRegistry()
    content = StudioContentService(
        cache,
        runtime=runtime,
        installation=installation,
        metrics=StudioContentMetrics(registry),
        cache_seconds=60,
    )
    return FeedbackForms(content), cache, registry


async def _resolve(forms: FeedbackForms, **overrides):
    arguments = dict(
        audience="guest",
        source="studio",
        tenant_id=TENANT,
        revision=OLD,
        locale="en",
        correlation_id="corr-1",
    )
    arguments.update(overrides)
    return await forms.resolve(**arguments)


async def test_a_bundled_form_needs_no_studio() -> None:
    forms, _, _ = _forms()

    resolved = await _resolve(forms, source="bundled", revision=None)

    assert resolved.rules == bundled_rules()
    assert resolved.revision is None


@pytest.mark.parametrize("locale", ["en", "en-GB", "EN"])
async def test_a_guest_answers_the_form_of_their_language(locale: str) -> None:
    forms, _, _ = _forms(Studio(_read(_body(OLD))))

    resolved = await _resolve(forms, locale=locale)

    assert resolved.revision == OLD
    assert [rule.id for rule in resolved.rules.questions] == [
        "translationQuality",
        "performance",
        "usability",
        "recommendation",
        "improvementIdeas",
    ]
    assert resolved.rules.snapshot[0]["question"]


@pytest.mark.parametrize("locale", ["ar", "de", "xx"])
async def test_a_language_studio_does_not_provide_has_no_studio_form(locale: str) -> None:
    forms, _, _ = _forms(Studio(_read(_body(OLD))))

    with pytest.raises(FeedbackFormChanged) as caught:
        await _resolve(forms, locale=locale)

    assert caught.value.reason == "form_missing"


async def test_staff_answer_the_staff_form() -> None:
    forms, _, _ = _forms(Studio(_read(_body(OLD))))

    resolved = await _resolve(forms, audience="staff", locale="de-DE")

    assert resolved.revision == OLD
    assert len(resolved.rules.questions) == 5


async def test_a_tenant_without_a_staff_form_has_no_studio_form() -> None:
    body = _body(OLD)
    body["staff"]["feedback"] = None
    forms, _, _ = _forms(Studio(_read(body)))

    with pytest.raises(FeedbackFormChanged):
        await _resolve(forms, audience="staff")


async def test_an_old_revision_still_held_is_the_form_the_answers_are_checked_against() -> None:
    clock = Clock()
    forms, cache, _ = _forms(Studio(_read(_without_usability(NEW))), clock=clock)
    cache.record(_read(_body(OLD)))
    cache.record(_read(_without_usability(NEW)))

    resolved = await _resolve(forms, revision=OLD)

    assert resolved.revision == OLD
    assert validate_answers(BUNDLED_ANSWERS, resolved.rules).numeric["usability"] == 3


async def test_an_unknown_revision_falls_back_to_the_latest_form_and_still_fits() -> None:
    forms, _, _ = _forms(Studio(_read(_body(NEW))))

    resolved = await _resolve(forms, revision="sha256:" + "c" * 64)

    assert resolved.revision == NEW
    assert validate_answers(BUNDLED_ANSWERS, resolved.rules)


async def test_an_unknown_revision_falls_back_to_a_latest_form_the_answers_no_longer_fit() -> None:
    forms, _, _ = _forms(Studio(_read(_without_usability(NEW))))

    resolved = await _resolve(forms, revision="sha256:" + "c" * 64)

    assert resolved.revision == NEW
    with pytest.raises(FeedbackFormChanged) as caught:
        validate_answers(BUNDLED_ANSWERS, resolved.rules)
    assert caught.value.reason == "unknown_question"


async def test_studio_down_with_nothing_held_is_unavailable_not_accepted() -> None:
    forms, _, _ = _forms(Studio(DOWN))

    with pytest.raises(FeedbackFormUnavailable):
        await _resolve(forms)


async def test_studio_unconfigured_is_unavailable() -> None:
    forms, _, _ = _forms(runtime=None)

    with pytest.raises(FeedbackFormUnavailable):
        await _resolve(forms, audience="staff")


async def test_studio_down_with_an_older_read_held_uses_it() -> None:
    clock = Clock()
    forms, cache, _ = _forms(Studio(DOWN), clock=clock)
    cache.record(_read(_body(NEW)))
    clock.now += 3600

    resolved = await _resolve(forms, revision="sha256:" + "c" * 64)

    assert resolved.revision == NEW


async def test_form_lookups_are_counted_under_their_own_endpoint() -> None:
    forms, _, registry = _forms(Studio(_read(_body(NEW))))

    await _resolve(forms, revision="sha256:" + "c" * 64)

    assert (
        registry.get_sample_value(
            "ssf_studio_content_fetch_total", {"endpoint": "feedback", "outcome": "live"}
        )
        == 1
    )


async def test_installation_feedback_uses_the_current_installation_form() -> None:
    forms, _, _ = _forms(installation=Studio(_installation(revision=NEW)))

    resolved = await _resolve(forms, audience="installation", tenant_id="default", revision=OLD)

    assert resolved.revision == NEW
    assert validate_answers(BUNDLED_ANSWERS, resolved.rules)


async def test_an_installation_without_a_form_has_no_studio_form() -> None:
    forms, _, _ = _forms(installation=Studio(_installation(with_form=False)))

    with pytest.raises(FeedbackFormChanged):
        await _resolve(forms, audience="installation", tenant_id="default")


async def test_installation_content_never_read_and_studio_down_is_unavailable() -> None:
    error = StudioRuntimeV2ClientError("studio_runtime_network_error", retryable=True)
    forms, _, _ = _forms(installation=Studio(error))

    with pytest.raises(FeedbackFormUnavailable):
        await _resolve(forms, audience="installation", tenant_id="default")


async def test_a_held_revision_is_counted_as_a_cached_answer() -> None:
    """Most submissions name a revision still held; the series must see them too."""
    forms, cache, registry = _forms(Studio(DOWN))
    cache.record(_read(_body(OLD)))

    await _resolve(forms, revision=OLD)

    assert (
        registry.get_sample_value(
            "ssf_studio_content_fetch_total", {"endpoint": "feedback", "outcome": "cached"}
        )
        == 1
    )
