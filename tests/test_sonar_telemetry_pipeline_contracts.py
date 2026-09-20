"""Behavioral guards for the telemetry and admission Sonar remediation."""

import asyncio
from dataclasses import replace

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import pipeline_admission
from services.api_gateway import quality_telemetry as quality
from services.api_gateway.feedback.crypto import FeedbackCipher, MissingEncryptionKey
from services.api_gateway.feedback.tenant import (
    ConfiguredTenantResolver,
    TenantResolver,
)
from tests.test_quality_telemetry_feedback import _event as feedback_event
from tests.test_quality_telemetry_session_lifecycle import _event as lifecycle_event
from tests.test_quality_telemetry_translation_message import _event as message_event
from tests.test_translation_inference_offload import load_translation


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["pipeline", "translation"])
async def test_abandoned_worker_is_catchable_without_running_work(monkeypatch, service):
    module = (
        pipeline_admission if service == "pipeline" else load_translation(monkeypatch)
    )
    admission = (
        module.PipelineAdmission(module.PipelineAdmissionConfig(max_concurrent=1))
        if service == "pipeline"
        else module.TranslationAdmission(max_concurrent=1)
    )
    queued = []
    ready = asyncio.Event()
    executed = []

    async def defer_worker(function):
        queued.append(function)
        ready.set()
        await asyncio.Future()

    monkeypatch.setattr(module.asyncio, "to_thread", defer_worker)
    task = asyncio.create_task(admission.run(lambda: executed.append(True)))
    await asyncio.wait_for(ready.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert admission.in_flight == 0

    try:
        queued[0]()
    except Exception as error:
        assert type(error) is module._WorkAbandoned
        assert str(error) == ""
    except BaseException:
        pytest.fail("abandoned application work bypasses except Exception")
    else:
        pytest.fail("abandoned worker did not signal cancellation")
    await asyncio.sleep(0)
    assert executed == []
    assert admission.in_flight == 0


@pytest.mark.parametrize("factory", [message_event, lifecycle_event, feedback_event])
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("session_ref", "session_ref is not an opaque reference"),
        ("tenant_ref", "tenant_ref is not a bounded tenant reference"),
    ],
)
def test_invalid_references_preserve_rejection_message(factory, field, message):
    event = factory()
    with pytest.raises(ValueError) as caught:
        replace(event, **{field: "untrusted reference"})
    assert str(caught.value) == message


@pytest.mark.parametrize("value", ["made_up", "SUCCESS", "success\n", ""])
def test_closed_enum_rejects_unknown_values(value):
    with pytest.raises(quality.DisallowedTelemetryValue):
        quality.enforce_value_shapes({"ssf.quality.terminal_outcome": value})


@pytest.mark.parametrize("value", ["١٢٣", "１２３", "12\n", "+12", "1.2"])
def test_numeric_attributes_remain_ascii_and_anchored(value):
    with pytest.raises(quality.DisallowedTelemetryValue):
        quality.enforce_value_shapes({"ssf.quality.total_duration_ms": value})


def _message_arguments():
    return dict(
        session_ref="a" * 32,
        tenant_ref="b" * 12,
        direction=quality.MessageDirection.CUSTOMER_TO_ADMIN,
        input_mode=quality.InputMode.AUDIO,
        source_lang="de",
        target_lang="en",
        terminal_outcome=quality.TerminalOutcome.SUCCESS,
        failed_stage=quality.PipelineStage.NONE,
        error_code=quality.QualityErrorCode.NONE,
        total_duration_ms=42,
        asr_duration_ms=10,
        translation_duration_ms=20,
        refinement_duration_ms=5,
        tts_duration_ms=7,
    )


def _telemetry(exports, mode=quality.TelemetryMode.ENABLED):
    def export(name, attributes, emitted_at):
        exports.append((name, attributes))

    return quality.QualityTelemetry(
        mode=mode, exporter=export, registry=CollectorRegistry()
    )


def test_translation_keyword_call_preserves_exported_taxonomy():
    exports = []
    result = _telemetry(exports).emit_translation_message(**_message_arguments())
    assert result.outcome is quality.ProbeOutcome.EMITTED
    assert len(exports) == 1
    name, attributes = exports[0]
    assert name == "translation_message"
    assert attributes.pop("ssf.quality.event_id") == str(result.event_id)
    assert attributes == {
        "ssf.quality.schema_version": "1",
        "ssf.quality.session_ref": "a" * 32,
        "ssf.quality.tenant_ref": "b" * 12,
        "ssf.quality.direction": "customer_to_admin",
        "ssf.quality.input_mode": "audio",
        "ssf.quality.source_lang": "de",
        "ssf.quality.target_lang": "en",
        "ssf.quality.terminal_outcome": "success",
        "ssf.quality.failed_stage": "none",
        "ssf.quality.error_code": "none",
        "ssf.quality.total_duration_ms": "42",
        "ssf.quality.asr_duration_ms": "10",
        "ssf.quality.translation_duration_ms": "20",
        "ssf.quality.refinement_duration_ms": "5",
        "ssf.quality.tts_duration_ms": "7",
    }


@pytest.mark.parametrize(
    "field",
    [
        "total_duration_ms",
        "asr_duration_ms",
        "translation_duration_ms",
        "refinement_duration_ms",
        "tts_duration_ms",
    ],
)
def test_translation_invalid_duration_is_dropped_without_export(field, caplog):
    exports = []
    arguments = _message_arguments()
    arguments[field] = "not a duration"
    result = _telemetry(exports).emit_translation_message(**arguments)
    assert result.outcome is quality.ProbeOutcome.DROPPED_DISALLOWED
    assert exports == []
    assert "Quality telemetry event rejected before export" in caplog.messages


@pytest.mark.parametrize("mode", list(quality.TelemetryMode))
@pytest.mark.parametrize("invalid_call", ["missing", "unexpected"])
def test_translation_duration_keywords_are_checked_even_when_disabled(
    mode, invalid_call
):
    arguments = _message_arguments()
    if invalid_call == "missing":
        del arguments["total_duration_ms"]
    else:
        arguments["unrecognized_duration_ms"] = 1
    telemetry = _telemetry([], mode=mode)
    with pytest.raises(TypeError):
        telemetry.emit_translation_message(**arguments)


@pytest.mark.asyncio
async def test_configured_resolver_preserves_awaitable_keyword_contract():
    resolver: TenantResolver = ConfiguredTenantResolver(tenant_id="configured")
    assert (
        await resolver.resolve(session_id="session", session_key=None) == "configured"
    )


@pytest.mark.parametrize("configured", ["%%%", "a", "é"])
def test_invalid_base64_preserves_encryption_configuration_error(
    monkeypatch, configured
):
    monkeypatch.setenv("SSF_FEEDBACK_ENCRYPTION_KEY", configured)
    with pytest.raises(MissingEncryptionKey) as caught:
        FeedbackCipher.from_environment()
    assert str(caught.value) == "SSF_FEEDBACK_ENCRYPTION_KEY must be base64-encoded"
