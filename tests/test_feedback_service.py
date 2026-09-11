"""FeedbackService: ordering, pseudonymisation, expiry, and analytics state.

The ordering pair (test_a_storage_failure_emits_nothing and
test_a_telemetry_failure_still_stores_the_feedback) is the contract: commit
first, emit second. Reorder the two calls and one of them fails.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from services.api_gateway.feedback.crypto import FeedbackCipher
from services.api_gateway.feedback.models import (
    MAX_IMPROVEMENTS_LENGTH,
    AnalyticsState,
    FeedbackSubmissionRequest,
    FeedbackTextTooLong,
)
from services.api_gateway.feedback.repository import FeedbackStorageUnavailable
from services.api_gateway.feedback.service import FeedbackService, UnknownSession
from services.api_gateway.feedback.tenant import ConfiguredTenantResolver
from services.api_gateway.quality_telemetry import ProbeOutcome, ProbeResult

FIXED_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, *, fails: bool = False) -> None:
        self.stored: list = []
        self.delivered: list = []
        self.marked_tenants: list = []
        self._fails = fails

    async def store(self, record) -> None:
        if self._fails:
            raise FeedbackStorageUnavailable("nope")
        self.stored.append(record)

    async def mark_analytics_delivered(self, feedback_id, tenant_id) -> None:
        # Positional, not defaulted: under row-level security an unbound update
        # matches nothing and reports success, so a fake that tolerates a
        # missing tenant would hide exactly the bug this argument prevents.
        self.delivered.append(feedback_id)
        self.marked_tenants.append(tenant_id)
        self.stored[-1] = replace(self.stored[-1], analytics_state=AnalyticsState.DELIVERED)

    async def mark_analytics_state(self, feedback_id, state, tenant_id) -> None:
        self.marked_tenants.append(tenant_id)
        self.stored[-1] = replace(self.stored[-1], analytics_state=state)

    async def claim_pending_analytics(self, limit):
        return []

    async def delete_expired(self, now, limit):
        return []


class FakeTelemetry:
    def __init__(self, outcome: ProbeOutcome = ProbeOutcome.EMITTED) -> None:
        self.calls: list = []
        self._outcome = outcome

    def emit_feedback_submitted(self, **kwargs) -> ProbeResult:
        self.calls.append(kwargs)
        return ProbeResult(self._outcome, kwargs.get("event_id"))


class FakeSessionManager:
    def __init__(self, known: bool = True) -> None:
        self._known = known

    def get_session(self, session_id):
        return SimpleNamespace(id=session_id) if self._known else None


def _service(**overrides):
    parts = dict(
        repository=FakeRepository(),
        cipher=FeedbackCipher(key=b"0" * 32),
        tenant_resolver=ConfiguredTenantResolver(tenant_id="tenant-a"),
        session_manager=FakeSessionManager(),
        telemetry=FakeTelemetry(),
    )
    parts.update(overrides)
    return FeedbackService(clock=lambda: FIXED_NOW, **parts), parts


def _request(**overrides) -> FeedbackSubmissionRequest:
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
    return FeedbackSubmissionRequest(**payload)


async def test_a_valid_submission_is_stored_and_returns_its_id() -> None:
    service, parts = _service()

    feedback_id = await service.submit(_request())

    assert isinstance(feedback_id, UUID)
    assert parts["repository"].stored[0].feedback_id == feedback_id


async def test_an_unknown_session_is_rejected_before_any_write() -> None:
    service, parts = _service(session_manager=FakeSessionManager(known=False))

    with pytest.raises(UnknownSession):
        await service.submit(_request())

    assert parts["repository"].stored == []


async def test_a_missing_session_stores_the_missing_reference() -> None:
    """Spec O1: the admin dashboard submits with no session at all."""
    service, parts = _service()

    await service.submit(_request(session_id=None))

    assert parts["repository"].stored[0].session_ref == "0" * 32


async def test_a_missing_session_is_not_an_unknown_session() -> None:
    """A null session is allowed; a session id that does not resolve is not."""
    service, _ = _service(session_manager=FakeSessionManager(known=False))

    assert await service.submit(_request(session_id=None))


async def test_text_over_the_limit_is_rejected_before_any_write() -> None:
    """Enforced here, not in Pydantic: a ValidationError echoes the input."""
    service, parts = _service()

    with pytest.raises(FeedbackTextTooLong):
        await service.submit(_request(improvements="x" * (MAX_IMPROVEMENTS_LENGTH + 1)))

    assert parts["repository"].stored == []


async def test_text_at_the_limit_is_accepted() -> None:
    service, parts = _service()

    await service.submit(_request(improvements="x" * MAX_IMPROVEMENTS_LENGTH))

    assert parts["repository"].stored


async def test_the_too_long_error_carries_no_copy_of_the_text() -> None:
    """The 422 is built from this exception; it must not carry the text."""
    service, _ = _service()
    secret = "SENTINEL-PURPLE-RHINOCEROS"
    text = secret + "x" * MAX_IMPROVEMENTS_LENGTH

    with pytest.raises(FeedbackTextTooLong) as caught:
        await service.submit(_request(improvements=text))

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


async def test_the_stored_text_is_encrypted() -> None:
    service, parts = _service()

    await service.submit(_request(improvements="a distinctive sentence"))

    ciphertext = parts["repository"].stored[0].improvements_ciphertext
    assert b"a distinctive sentence" not in ciphertext


async def test_the_stored_text_round_trips_for_authorised_reads() -> None:
    """Encrypted, not destroyed: retained feedback must stay readable."""
    service, parts = _service()
    cipher = FeedbackCipher(key=b"0" * 32)

    await service.submit(_request(improvements="a distinctive sentence"))
    record = parts["repository"].stored[0]

    assert (
        cipher.decrypt(
            record.improvements_ciphertext,
            feedback_id=record.feedback_id,
            tenant_id=record.tenant_id,
        )
        == "a distinctive sentence"
    )


async def test_empty_text_stores_null_not_an_empty_ciphertext() -> None:
    service, parts = _service()

    await service.submit(_request(improvements=None))

    assert parts["repository"].stored[0].improvements_ciphertext is None


async def test_blank_text_stores_null() -> None:
    """An empty string is not a submission; it should not become ciphertext."""
    service, parts = _service()

    await service.submit(_request(improvements="   "))

    assert parts["repository"].stored[0].improvements_ciphertext is None


async def test_expiry_is_twelve_months_after_creation() -> None:
    service, parts = _service()

    await service.submit(_request())

    record = parts["repository"].stored[0]
    assert record.created_at == FIXED_NOW
    assert record.expires_at == datetime(2027, 9, 9, 12, 0, tzinfo=timezone.utc)


async def test_expiry_survives_a_leap_day() -> None:
    """29 February plus twelve months has no 29 February to land on."""
    leap = datetime(2028, 2, 29, 9, 0, tzinfo=timezone.utc)
    service, parts = _service()
    service._clock = lambda: leap  # noqa: SLF001 - pinning the clock

    await service.submit(_request())

    assert parts["repository"].stored[0].expires_at == datetime(
        2029, 2, 28, 9, 0, tzinfo=timezone.utc
    )


async def test_the_session_reference_is_derived_not_accepted() -> None:
    service, parts = _service()

    await service.submit(_request(session_id="ABC12345"))

    record = parts["repository"].stored[0]
    assert record.session_ref != "ABC12345"
    assert len(record.session_ref) == 32


async def test_the_retention_policy_version_is_recorded() -> None:
    """#305 must not retroactively move an existing record's expiry."""
    service, parts = _service()

    await service.submit(_request())

    assert parts["repository"].stored[0].retention_policy_version == "v1-12-months"


async def test_the_consent_snapshot_records_the_submitted_form_version() -> None:
    service, parts = _service()

    await service.submit(_request(form_version="v1"))

    snapshot = parts["repository"].stored[0].consent_snapshot
    assert snapshot["form_version"] == "v1"
    assert snapshot["manifestation"] == "form_submission"


async def test_telemetry_receives_the_stored_event_id() -> None:
    """The reconciler re-emits this id; a second one would double-count."""
    service, parts = _service()

    await service.submit(_request())

    record = parts["repository"].stored[0]
    assert parts["telemetry"].calls[0]["event_id"] == record.analytics_event_id


async def test_telemetry_never_receives_the_free_text() -> None:
    service, parts = _service()

    await service.submit(_request(improvements="a distinctive sentence"))

    assert "a distinctive sentence" not in str(parts["telemetry"].calls)


async def test_telemetry_never_receives_the_raw_session_id() -> None:
    service, parts = _service()

    await service.submit(_request(session_id="ABC12345"))

    assert "ABC12345" not in str(parts["telemetry"].calls)


async def test_a_storage_failure_emits_nothing() -> None:
    """Half the ordering contract: no event may describe an absent row."""
    service, parts = _service(repository=FakeRepository(fails=True))

    with pytest.raises(FeedbackStorageUnavailable):
        await service.submit(_request())

    assert parts["telemetry"].calls == []


async def test_a_telemetry_failure_still_stores_the_feedback() -> None:
    """The other half: a Collector outage is not an API failure."""
    service, parts = _service(telemetry=FakeTelemetry(ProbeOutcome.EXPORT_FAILED))

    feedback_id = await service.submit(_request())

    assert parts["repository"].stored[0].feedback_id == feedback_id
    assert parts["repository"].stored[0].analytics_state is AnalyticsState.PENDING


async def test_a_rejected_event_stays_pending() -> None:
    service, parts = _service(telemetry=FakeTelemetry(ProbeOutcome.DROPPED_DISALLOWED))

    await service.submit(_request())

    assert parts["repository"].stored[0].analytics_state is AnalyticsState.PENDING


async def test_a_delivered_event_is_marked_delivered() -> None:
    service, parts = _service()

    feedback_id = await service.submit(_request())

    assert parts["repository"].delivered == [feedback_id]


async def test_the_delivery_mark_carries_the_rows_own_tenant() -> None:
    """The row-level policy filters this update; the wrong tenant is a no-op.

    Passing a tenant that does not match the stored row would leave every
    submission `pending` forever without any error, so the value has to be the
    one the record was written with -- not a default and not a guess.
    """
    service, parts = _service()

    await service.submit(_request())

    stored = parts["repository"].stored[0]
    assert parts["repository"].marked_tenants == [stored.tenant_id]
    assert parts["repository"].stored[0].analytics_state is AnalyticsState.DELIVERED


async def test_disabled_telemetry_is_not_a_reconciliation_backlog() -> None:
    service, parts = _service(telemetry=FakeTelemetry(ProbeOutcome.DISABLED))

    await service.submit(_request())

    state = parts["repository"].stored[0].analytics_state
    assert state is AnalyticsState.NOT_APPLICABLE


class TestTheRealTelemetrySeam:
    """The service against the real QualityTelemetry, not FakeTelemetry.

    FakeTelemetry accepts `**kwargs`, so it agrees with any call the service
    makes. That is what let #304's emitter -- which takes `feedback_ref` --
    coexist on this branch with a service still passing `feedback_id`: every
    unit test passed while a real submission raised TypeError after the row
    had already committed, answering 500 and emitting nothing.

    The row is committed before emission, so a signature drift here does not
    lose the feedback; it loses the analytics event and the customer's
    confirmation. Only a test holding both real objects can see it.
    """

    async def test_a_submission_reaches_the_real_emitter(self) -> None:
        from prometheus_client import CollectorRegistry

        from services.api_gateway.quality_telemetry import QualityTelemetry, TelemetryMode

        exported: list = []
        telemetry = QualityTelemetry(
            mode=TelemetryMode.ENABLED,
            exporter=lambda name, attributes, emitted_at_utc: exported.append(
                (name, dict(attributes))
            ),
            registry=CollectorRegistry(),
        )
        service, parts = _service(telemetry=telemetry)

        feedback_id = await service.submit(_request())

        assert exported, "the real emitter was never reached"
        name, attributes = exported[0]
        assert name == "feedback_submitted"
        assert parts["repository"].delivered == [feedback_id]

    async def test_it_emits_the_feedback_reference_not_the_feedback_id(self) -> None:
        """A raw feedback id in ClickHouse would join the two stores directly."""
        from prometheus_client import CollectorRegistry

        from services.api_gateway.quality_telemetry import QualityTelemetry, TelemetryMode
        from services.api_gateway.session_pseudonym import feedback_ref

        exported: list = []
        telemetry = QualityTelemetry(
            mode=TelemetryMode.ENABLED,
            exporter=lambda name, attributes, emitted_at_utc: exported.append(
                (name, dict(attributes))
            ),
            registry=CollectorRegistry(),
        )
        service, _ = _service(telemetry=telemetry)

        feedback_id = await service.submit(_request())

        attributes = exported[0][1]
        assert attributes["ssf.quality.feedback_ref"] == feedback_ref(feedback_id)
        assert str(feedback_id) not in str(attributes)
