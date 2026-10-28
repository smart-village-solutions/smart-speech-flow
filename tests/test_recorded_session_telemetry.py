"""A recorded session's telemetry cannot be joined to its archive (spec §5.5)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from services.api_gateway import pipeline_logic
from services.api_gateway.message_telemetry import MessageTelemetryRecorder
from services.api_gateway.quality_telemetry_schema import InputMode
from services.api_gateway.recording.session_service import RecordingSessions
from services.api_gateway.session_models import ClientType
from services.api_gateway.session_pseudonym import RECORDED_MARK_SECONDS, SessionPseudonymizer
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.translation_refiner import (
    OllamaTranslationRefiner,
    RefinementOutcome,
    ShadowComparisonRefiner,
)
from tests.recording_archive_fakes import say_yes
from tests.test_recording_session_service import KEY, Harness

SESSION = "ABCD1234"


class Telemetry:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []

    def emit_translation_message(self, **fields: Any) -> None:
        self.messages.append(fields)

    def emit_refinement_attempt(self, **fields: Any) -> None:
        self.attempts.append(fields)


def _pseudonymizer() -> SessionPseudonymizer:
    return SessionPseudonymizer(key=b"k" * 32)


def test_a_recorded_session_keeps_a_random_reference_a_day_past_its_end() -> None:
    now = [1000.0]
    pseudonymizer = SessionPseudonymizer(key=b"k" * 32, clock=lambda: now[0])
    keyed = pseudonymizer.reference(SESSION)

    pseudonymizer.mark_recorded(SESSION)
    recorded = pseudonymizer.reference(SESSION)

    assert pseudonymizer.is_recorded(SESSION)
    assert recorded not in (keyed, pseudonymizer.recording_reference(SESSION))
    assert len(recorded) == len(keyed) and int(recorded, 16) >= 0
    pseudonymizer.mark_recorded(SESSION)
    assert pseudonymizer.reference(SESSION) == recorded  # stable within the session
    assert _pseudonymizer().reference(SESSION) == keyed  # nothing else is affected

    pseudonymizer.ended(SESSION)
    now[0] += RECORDED_MARK_SECONDS - 1  # late messages and guest feedback still come in
    assert pseudonymizer.reference(SESSION) == recorded

    now[0] += 1
    assert pseudonymizer.reference(SESSION) == keyed
    assert not pseudonymizer.is_recorded(SESSION)
    pseudonymizer.mark_recorded("OTHER123")  # any mark sweeps out expired ones
    assert SESSION not in pseudonymizer._recorded


@pytest.mark.parametrize("recorded", [False, True])
def test_a_message_row_of_a_recorded_session_names_no_language(recorded) -> None:
    pseudonymizer, telemetry = _pseudonymizer(), Telemetry()
    key = TenantSessionKey("tenant-kassel", SESSION)
    recorder = MessageTelemetryRecorder(
        session_id=key, start_time=time.perf_counter(), pseudonymizer=pseudonymizer
    )
    recorder.arm(InputMode.TEXT)
    recorder.record_request(client_type=ClientType.CUSTOMER, source_lang="ar", target_lang="de")
    if recorded:
        pseudonymizer.mark_recorded(SESSION)

    recorder.emit(telemetry)

    [row] = telemetry.messages
    expected = ("und", "und") if recorded else ("ar", "de")
    assert (row["source_lang"], row["target_lang"]) == expected
    assert row["session_ref"] == pseudonymizer.reference(SESSION)


class _Refiner(OllamaTranslationRefiner):
    def _perform_refinement(self, *args: Any, **kwargs: Any) -> RefinementOutcome:
        return RefinementOutcome(text="x", changed=False, latency_ms=1.0)


@pytest.mark.parametrize(("withheld", "expected"), [(True, "und"), (False, "ar")])
def test_a_refinement_attempt_of_a_recorded_session_names_no_language(withheld, expected):
    telemetry = Telemetry()
    refiner = _Refiner("http://ollama:11434", "gpt-oss:20b", 4.0, 0.7, 1, False)
    refiner.attach_quality_telemetry(telemetry)

    refiner.refine("x", "ar", "de", context={"withhold_languages": withheld})

    assert telemetry.attempts[0]["source_lang"] == expected


def test_a_shadow_candidate_of_a_recorded_session_names_no_language(monkeypatch):
    telemetry = Telemetry()
    refiner = ShadowComparisonRefiner(
        "http://ollama:11434",
        "gpt-oss:20b",
        4.0,
        0.7,
        1,
        False,
        candidate_model="phi4-mini",
        queue_limit=4,
    )
    refiner.attach_quality_telemetry(telemetry)
    monkeypatch.setattr(
        "services.api_gateway.translation_refiner.OllamaTranslationRefiner", _Refiner
    )
    refiner.pending = 1

    refiner._run_candidate("x", "ar", "de", context={"withhold_languages": True})

    assert (telemetry.attempts[0]["source_lang"], telemetry.attempts[0]["target_lang"]) == (
        "und",
        "und",
    )


def test_the_pipeline_tells_the_refiner_to_withhold_languages(monkeypatch) -> None:
    contexts: list[dict[str, Any]] = []

    class Capturing:
        is_active = True

        def refine(self, text, source_lang, target_lang, context=None):
            contexts.append(context)
            return RefinementOutcome(text=text, changed=False, latency_ms=0.0)

    run = pipeline_logic._start_run(
        "text",
        "ar",
        "de",
        session_id=SESSION,
        debug=False,
        input_size={},
        withhold_languages=True,
    )
    run.translation_text = "Hallo"
    pipeline_logic._refine(run, Capturing())

    assert contexts[0]["withhold_languages"] is True


@pytest.fixture
def h(tmp_path) -> Harness:
    harness = Harness(tmp_path)
    harness.pseudonymizer = _pseudonymizer()
    harness.service._pseudonymizer = harness.pseudonymizer
    return harness


async def test_the_first_yes_makes_the_session_recorded_and_its_end_starts_the_clock(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    assert not h.pseudonymizer.is_recorded(KEY.session_id)

    await say_yes(h.service, KEY, "r1")
    assert h.pseudonymizer.is_recorded(KEY.session_id)

    await h.service.session_ended(KEY)
    assert h.pseudonymizer._recorded[KEY.session_id][1] is not None


async def test_the_end_starts_the_clock_even_when_the_state_store_fails(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    await say_yes(h.service, KEY, "r1")

    async def broken(_key):
        raise ConnectionError("redis down")

    h.store.load = broken
    with pytest.raises(ConnectionError):
        await h.service.session_ended(KEY)

    assert h.pseudonymizer._recorded[KEY.session_id][1] is not None


async def test_a_no_leaves_the_session_unrecorded(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    await h.service.answer(KEY, request_id="r1", consent=False)
    await h.service.accept(KEY)
    assert not h.pseudonymizer.is_recorded(KEY.session_id)


async def test_after_a_restart_a_message_learns_the_session_was_recorded(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp")
    await say_yes(h.service, KEY, "r1")
    restarted = _pseudonymizer()
    service = RecordingSessions(
        store=h.store,
        announcer=h.announcer,
        policy=h._read_policy,
        recovery_key_ready=h._recovery_ready,
        audit=h._append,
        archive=h.rig.archive,
        pseudonymizer=restarted,
    )

    await service.accept(KEY)

    assert restarted.is_recorded(KEY.session_id)


class LifecycleSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def emit_session_lifecycle(self, **fields: Any) -> None:
        self.calls.append(fields)


def _manager_with_spy(tmp_path):
    from services.api_gateway.audio_storage import AudioStore
    from services.api_gateway.session_manager import TenantSessionManager
    from services.api_gateway.session_store import MemoryTenantSessionStore

    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore(tmp_path),
        pseudonymizer=_pseudonymizer(),
        session_id_factory=lambda: SESSION,
    )
    spy = LifecycleSpy()
    manager.attach_quality_telemetry(spy)
    return manager, spy


async def test_a_recorded_sessions_end_event_says_nothing_that_dates_or_sizes_it(tmp_path):
    from datetime import timedelta

    from tests.test_session_content_removal import _message

    manager, spy = _manager_with_spy(tmp_path)
    session = await manager.create_admin_session("tenant-kassel", "rev")
    for message_id in ("m1", "m2"):
        await manager.add_message(session.key, _message(message_id))
    session.created_at -= timedelta(hours=1)
    manager.pseudonymizer.mark_recorded(SESSION)

    await manager.terminate_session(session.key, "manual_termination")

    ended = spy.calls[-1]
    assert ended["session_ref"] == manager.pseudonymizer.reference(SESSION)
    assert (ended["session_duration_ms"], ended["message_count"]) == (0, 0)


async def test_termination_asks_recording_whether_the_session_was_recorded(tmp_path):
    """After a restart only the recording state remembers it (spec §5.5)."""
    manager, spy = _manager_with_spy(tmp_path)
    session = await manager.create_admin_session("tenant-kassel", "rev")
    keyed = manager.pseudonymizer.reference(SESSION)

    class Recording:
        async def note_recorded(self, key):
            manager.pseudonymizer.mark_recorded(key.session_id)

        async def session_ended(self, key):
            return None

    manager.recording = Recording()
    await manager.terminate_session(session.key, "manual_termination")

    assert spy.calls[-1]["session_ref"] != keyed


async def test_guest_feedback_of_a_recorded_session_names_no_language() -> None:
    from tests.test_feedback_service import _service, _v2

    service, parts = _service()
    parts["pseudonymizer"].mark_recorded("ABC12345")

    await service.submit(
        _v2(form_source="bundled", configuration_revision=None, locale="ar"),
        correlation_id="c-1",
    )

    record = parts["repository"].stored[0]
    assert record.form_locale is None
    assert record.session_ref == parts["pseudonymizer"].reference("ABC12345")
