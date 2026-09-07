"""`translation_message` on the live message route (tasks 2.3, 2.4, 4.3).

The emitter's own guarantees were proven against the emitter. These prove them
where they matter: driving `send_unified_message`, with a real QualityTelemetry
whose exporter is dead, and asserting the request returns exactly what it would
have returned with telemetry switched off.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    InputMode,
    MessageDirection,
    PipelineStage,
    QualityErrorCode,
    QualityTelemetry,
    TelemetryMode,
    TerminalOutcome,
    discard_event,
)
from services.api_gateway.routes import session as session_routes
from services.api_gateway.session_manager import SessionManager, SessionStatus
from tests.pipeline_helpers import AUDIO_BYTES, make_active_session

TRANSCRIPT = "Guten Tag"
TRANSLATION = "Good day"
UPSTREAM_DETAIL = "HTTPConnectionPool(host='asr', port=8001): Max retries exceeded"


@pytest.fixture
def manager():
    return SessionManager()


class _CapturingExporter:
    def __init__(self):
        self.calls = []

    def __call__(self, name, attributes, emitted_at_utc):
        self.calls.append((name, dict(attributes)))

    @property
    def messages(self):
        return [a for name, a in self.calls if name == "translation_message"]


def _dead_exporter(name, attributes, emitted_at_utc):
    raise RuntimeError("ClickHouse is unreachable")


def _telemetry(exporter, mode=TelemetryMode.ENABLED):
    return QualityTelemetry(mode=mode, exporter=exporter, registry=CollectorRegistry())


def _request(content_type: str, telemetry) -> Mock:
    request = Mock()
    request.app.state.pipeline_admission = None
    request.app.state.quality_telemetry = telemetry
    request.headers = {"content-type": content_type}
    if content_type.startswith("application/json"):
        request.json = AsyncMock(
            return_value={
                "text": TRANSCRIPT,
                "source_lang": "de",
                "target_lang": "en",
                "client_type": "admin",
            }
        )
    else:
        handle = Mock()
        handle.read = AsyncMock(return_value=AUDIO_BYTES)
        request.form = AsyncMock(
            return_value={
                "file": handle,
                "source_lang": "de",
                "target_lang": "en",
                "client_type": "admin",
            }
        )
    return request


def _without_timestamp(detail):
    return {k: v for k, v in detail.items() if k != "timestamp"}


def _debug(failed_stage="none", error_code="none"):
    return {
        "failed_stage": failed_stage,
        "error_code": error_code,
        "steps": [
            {"step": "ASR", "output": TRANSCRIPT, "duration_ms": 910},
            {"step": "Translation", "output": TRANSLATION, "duration_ms": 420},
            {"step": "TTS", "input": {"text": TRANSLATION}, "duration_ms": 830},
        ],
    }


def _success():
    return {
        "error": False,
        "asr_text": TRANSCRIPT,
        "translation_text": TRANSLATION,
        "audio_bytes": b"audio",
        "debug": _debug(),
    }


def _failure():
    return {
        "error": True,
        "error_msg": f"ASR-Fehler: {UPSTREAM_DETAIL}",
        "asr_text": None,
        "translation_text": None,
        "audio_bytes": None,
        "debug": _debug(failed_stage="asr", error_code="upstream_unreachable"),
    }


async def _send(manager, telemetry, *, content_type, pipeline_result):
    session_id = await make_active_session(manager)
    target = "process_wav" if "multipart" in content_type else "process_text_pipeline"
    with (
        patch.object(session_routes, "session_manager", manager),
        patch.object(session_routes, target, return_value=pipeline_result),
        patch.object(session_routes, "_store_audio_artifacts", return_value=None),
    ):
        return await session_routes.send_unified_message(
            session_id, _request(content_type, telemetry)
        )


class TestOneRowPerMessage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_type,mode",
        [
            ("multipart/form-data; boundary=b", InputMode.AUDIO),
            ("application/json", InputMode.TEXT),
        ],
    )
    async def test_a_successful_message_emits_exactly_one_row(
        self, manager, content_type, mode
    ):
        exporter = _CapturingExporter()

        response = await _send(
            manager,
            _telemetry(exporter),
            content_type=content_type,
            pipeline_result=_success(),
        )

        assert response.status == "success"
        assert len(exporter.messages) == 1
        assert exporter.messages[0]["ssf.quality.input_mode"] == mode.value
        assert (
            exporter.messages[0]["ssf.quality.terminal_outcome"]
            == TerminalOutcome.SUCCESS.value
        )

    @pytest.mark.asyncio
    async def test_the_row_carries_the_stage_durations_the_pipeline_measured(
        self, manager
    ):
        exporter = _CapturingExporter()

        await _send(
            manager,
            _telemetry(exporter),
            content_type="multipart/form-data; boundary=b",
            pipeline_result=_success(),
        )

        attributes = exporter.messages[0]
        assert attributes["ssf.quality.asr_duration_ms"] == "910"
        assert attributes["ssf.quality.translation_duration_ms"] == "420"
        assert attributes["ssf.quality.tts_duration_ms"] == "830"
        assert int(attributes["ssf.quality.total_duration_ms"]) >= 0

    @pytest.mark.asyncio
    async def test_the_sending_client_is_recorded_as_the_direction(self, manager):
        exporter = _CapturingExporter()

        await _send(
            manager,
            _telemetry(exporter),
            content_type="application/json",
            pipeline_result=_success(),
        )

        assert (
            exporter.messages[0]["ssf.quality.direction"]
            == MessageDirection.ADMIN_TO_CUSTOMER.value
        )

    @pytest.mark.asyncio
    async def test_a_failed_message_emits_a_failure_row(self, manager):
        exporter = _CapturingExporter()

        with pytest.raises(HTTPException):
            await _send(
                manager,
                _telemetry(exporter),
                content_type="multipart/form-data; boundary=b",
                pipeline_result=_failure(),
            )

        attributes = exporter.messages[0]
        assert (
            attributes["ssf.quality.terminal_outcome"] == TerminalOutcome.FAILURE.value
        )
        assert attributes["ssf.quality.failed_stage"] == PipelineStage.ASR.value
        assert (
            attributes["ssf.quality.error_code"]
            == QualityErrorCode.UPSTREAM_UNREACHABLE.value
        )

    @pytest.mark.asyncio
    async def test_a_request_that_never_became_a_message_emits_nothing(self, manager):
        exporter = _CapturingExporter()

        with patch.object(session_routes, "session_manager", manager):
            with pytest.raises(HTTPException) as excinfo:
                await session_routes.send_unified_message(
                    "no-such-session",
                    _request("application/json", _telemetry(exporter)),
                )

        assert excinfo.value.status_code == 404
        assert exporter.messages == []

    @pytest.mark.asyncio
    async def test_an_unsupported_content_type_emits_nothing(self, manager):
        exporter = _CapturingExporter()
        session_id = await make_active_session(manager)

        with patch.object(session_routes, "session_manager", manager):
            with pytest.raises(HTTPException):
                await session_routes.send_unified_message(
                    session_id, _request("text/plain", _telemetry(exporter))
                )

        assert exporter.messages == []


class TestNoContentLeavesTheGateway:
    @pytest.mark.asyncio
    async def test_no_transcript_translation_or_upstream_detail_is_emitted(
        self, manager
    ):
        exporter = _CapturingExporter()

        with pytest.raises(HTTPException):
            await _send(
                manager,
                _telemetry(exporter),
                content_type="multipart/form-data; boundary=b",
                pipeline_result=_failure(),
            )

        emitted = " ".join(exporter.messages[0].values())
        assert TRANSCRIPT not in emitted
        assert TRANSLATION not in emitted
        assert "asr" not in emitted.replace("asr_duration_ms", "").replace(
            PipelineStage.ASR.value, ""
        )
        assert "8001" not in emitted

    @pytest.mark.asyncio
    async def test_the_session_id_is_not_recoverable_from_the_row(self, manager):
        exporter = _CapturingExporter()
        session_id = await make_active_session(manager)

        with (
            patch.object(session_routes, "session_manager", manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=_success()
            ),
        ):
            await session_routes.send_unified_message(
                session_id, _request("application/json", _telemetry(exporter))
            )

        assert session_id not in exporter.messages[0].values()


class TestTelemetryNeverChangesTheOutcome:
    """Task 2.4 and 4.3, against the message path rather than the emitter."""

    @pytest.mark.asyncio
    async def test_a_dead_clickhouse_still_returns_the_translation(self, manager):
        response = await _send(
            manager,
            _telemetry(_dead_exporter),
            content_type="multipart/form-data; boundary=b",
            pipeline_result=_success(),
        )

        assert response.status == "success"
        assert response.translated_text == TRANSLATION

    @pytest.mark.asyncio
    async def test_a_dead_clickhouse_reports_a_failure_the_same_way(self, manager):
        with pytest.raises(HTTPException) as with_dead_exporter:
            await _send(
                manager,
                _telemetry(_dead_exporter),
                content_type="multipart/form-data; boundary=b",
                pipeline_result=_failure(),
            )

        with pytest.raises(HTTPException) as with_telemetry_off:
            await _send(
                manager,
                _telemetry(discard_event, mode=TelemetryMode.DISABLED),
                content_type="multipart/form-data; boundary=b",
                pipeline_result=_failure(),
            )

        assert (
            with_dead_exporter.value.status_code == with_telemetry_off.value.status_code
        )
        # Everything but the envelope's own wall-clock timestamp, which differs
        # between any two responses.
        assert _without_timestamp(
            with_dead_exporter.value.detail
        ) == _without_timestamp(with_telemetry_off.value.detail)

    @pytest.mark.asyncio
    async def test_a_gateway_with_no_telemetry_wired_up_still_serves(self, manager):
        request = _request("application/json", None)

        session_id = await make_active_session(manager)
        with (
            patch.object(session_routes, "session_manager", manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=_success()
            ),
        ):
            response = await session_routes.send_unified_message(session_id, request)

        assert response.status == "success"

    @pytest.mark.asyncio
    async def test_an_emitter_that_raises_outright_does_not_reach_the_caller(
        self, manager
    ):
        exploding = Mock()
        exploding.emit_translation_message.side_effect = RuntimeError("boom")

        response = await _send(
            manager,
            exploding,
            content_type="application/json",
            pipeline_result=_success(),
        )

        assert response.status == "success"

    @pytest.mark.asyncio
    async def test_production_default_emits_nothing_at_all(self, manager):
        """Production runs `disabled`; merging this must change nothing there."""
        exporter = _CapturingExporter()

        response = await _send(
            manager,
            _telemetry(exporter, mode=TelemetryMode.DISABLED),
            content_type="application/json",
            pipeline_result=_success(),
        )

        assert response.status == "success"
        assert exporter.calls == []
