"""Every broad exception handler in production code is on purpose (#230).

A handler is broad when it is bare or catches Exception or BaseException, alone or
in a tuple. Each one is listed under its module and qualified function, with one
reason per handler in source order:

- fallback: degrades to a stated default so the caller keeps working;
- boundary: the edge of a loop, task, socket, endpoint or callback, where an
  escaping error would end something long-lived or lose an answer;
- bookkeeping-reraise: records or undoes something, then re-raises.

A catch-all that only reshapes an error into a 500 belongs to none of these: the
gateway's UnhandledErrorMiddleware already answers that.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
BROAD = {"Exception", "BaseException"}
REASONS = {"fallback", "boundary", "bookkeeping-reraise"}

ALLOWED: dict[tuple[str, str], list[str]] = {
    # records the breaker failure, then re-raises
    ("services/api_gateway/ai_service_client.py", "call_ai_service"): ["bookkeeping-reraise"],
    # one failed timeout pass must not end the monitor
    ("services/api_gateway/background_tasks.py", "session_timeout_monitor"): ["boundary"],
    # one failed retention pass must not end retention
    ("services/api_gateway/background_tasks.py", "_step"): ["boundary"],
    # feedback stays off (503) and is retried
    ("services/api_gateway/feedback/wiring.py", "_connect_feedback_request_path"): ["fallback"],
    # Studio feedback reads stay off (503) and are retried
    ("services/api_gateway/feedback/wiring.py", "_connect_feedback_read_path"): ["fallback"],
    # maintenance stays off and is retried
    ("services/api_gateway/feedback/wiring.py", "_connect_feedback_maintenance"): ["fallback"],
    # the connect retry loop survives any one attempt
    ("services/api_gateway/feedback/wiring.py", "feedback_connect_task"): ["boundary"],
    # the maintenance loop survives any one pass
    ("services/api_gateway/feedback/wiring.py", "feedback_maintenance_task"): ["boundary"],
    # a daemon-thread target hands its failure back to the loop
    ("services/api_gateway/app.py", "_shutdown_quality_telemetry.run"): ["boundary"],
    # telemetry off rather than no gateway
    ("services/api_gateway/app.py", "_build_quality_telemetry"): ["fallback"],
    # teardown carries on past one failing step
    ("services/api_gateway/app.py", "_shut_down"): ["boundary"],
    # unnormalised audio when normalisation fails
    ("services/api_gateway/audio_processing.py", "normalize_audio"): ["fallback"],
    # one unremovable file must not stop the sweep
    ("services/api_gateway/audio_storage.py", "_delete_expired"): ["boundary"],
    # one unreadable file must not stop the count
    ("services/api_gateway/audio_storage.py", "get_disk_usage"): ["boundary"],
    # applies the failure to the breaker, then re-raises
    ("services/api_gateway/circuit_breaker.py", "CircuitBreaker.call"): ["bookkeeping-reraise"],
    # a state-change callback must not fail the call
    ("services/api_gateway/circuit_breaker.py", "CircuitBreaker._notify_state_change"): [
        "boundary"
    ],
    # an unavailable pass, never a raise
    ("services/api_gateway/feedback/maintenance.py", "FeedbackMaintenance.reconcile_once"): [
        "fallback"
    ],
    # one bad row must not end the batch
    ("services/api_gateway/feedback/maintenance.py", "FeedbackMaintenance._redeliver"): [
        "boundary",
        "boundary",
    ],
    # a failed pass is reported; the backlog count after a committed deletion is optional
    ("services/api_gateway/feedback/maintenance.py", "FeedbackMaintenance.expire_once"): [
        "fallback",
        "fallback",
    ],
    # a committed row stays pending for the reconciler, whether emitting or
    # marking it raised
    ("services/api_gateway/feedback/service.py", "FeedbackService._emit"): [
        "fallback",
        "fallback",
    ],
    # one dead socket must not stop the others' notice
    (
        "services/api_gateway/legacy_session_manager.py",
        "LegacySessionManager._send_termination_notifications",
    ): ["boundary"],
    # no original-audio URL rather than a failed message
    ("services/api_gateway/message_requests.py", "_store_audio_artifacts"): ["fallback"],
    # records the telemetry failure and session, then re-raises
    ("services/api_gateway/message_processing.py", "send_unified_message"): ["bookkeeping-reraise"],
    # a stored message is not failed by its broadcast or its authorization write-back
    ("services/api_gateway/message_delivery.py", "create_session_message"): [
        "boundary",
        "fallback",
    ],
    # no reply audio rather than a failed message
    ("services/api_gateway/message_requests.py", "_store_translated_audio"): ["fallback"],
    # telemetry must never reach the caller
    ("services/api_gateway/message_telemetry.py", "MessageTelemetryRecorder.emit"): ["boundary"],
    # the raw body when an error reply is not JSON
    ("services/api_gateway/pipeline_results.py", "_upstream_error_message"): ["fallback"],
    # the raw body when an error reply is not JSON
    ("services/api_gateway/pipeline_logic.py", "_tts_error_message"): ["fallback"],
    # the worker-thread edge: any stage error becomes a classified result
    ("services/api_gateway/pipeline_logic.py", "process_text_pipeline"): ["boundary"],
    # the worker-thread edge: any stage error becomes a classified result
    ("services/api_gateway/pipeline_logic.py", "process_wav"): ["boundary"],
    # a pluggable exporter must not break the emitter
    ("services/api_gateway/quality_telemetry.py", "QualityTelemetry._export"): ["boundary"],
    # the same, per event of one feedback submission
    ("services/api_gateway/quality_telemetry.py", "QualityTelemetry.emit_feedback"): ["boundary"],
    # one socket send
    (
        "services/api_gateway/realtime_client_status.py",
        "ClientStatusHandler.send_polling_interval_update",
    ): ["boundary"],
    # one socket send
    (
        "services/api_gateway/realtime_client_status.py",
        "ClientStatusHandler.send_battery_saver_notification",
    ): ["boundary"],
    # one recipient must not stop the fan-out
    ("services/api_gateway/realtime_dispatch.py", "BroadcastDispatcher.broadcast_to_session"): [
        "boundary"
    ],
    # one recipient must not stop the fan-out
    (
        "services/api_gateway/realtime_dispatch.py",
        "BroadcastDispatcher.broadcast_with_differentiated_content",
    ): ["boundary"],
    # one failed pass must not end heartbeats
    ("services/api_gateway/realtime_heartbeat.py", "Heartbeat.monitor_loop"): ["boundary"],
    # one dead socket is released, the rest still pinged
    ("services/api_gateway/realtime_heartbeat.py", "Heartbeat.send_pings"): ["boundary"],
    # fail closed: refuse the write, never raise
    ("services/api_gateway/runtime_policy.py", "RuntimePolicyGate._decide"): ["fallback"],
    # one failed pass must not end polling
    ("services/api_gateway/service_health.py", "ServiceHealthManager._health_check_loop"): [
        "boundary"
    ],
    # a failed probe marks the service down
    ("services/api_gateway/service_health.py", "ServiceHealthManager._check_service_health"): [
        "fallback"
    ],
    # telemetry must not decide whether a session opens
    ("services/api_gateway/session_manager.py", "SessionManagerBase._emit_lifecycle"): ["fallback"],
    # one session must not stop the retention sweep
    ("services/api_gateway/session_manager.py", "SessionManagerBase.sweep_expired_content"): [
        "boundary"
    ],
    # rolls the in-memory change back, then re-raises
    ("services/api_gateway/session_manager.py", "SessionManagerBase._sweep_session_content"): [
        "bookkeeping-reraise"
    ],
    # display content must never cost a persistence read, nor a content route a 500
    ("services/api_gateway/studio_content.py", "StudioContentCache.try_record"): ["fallback"],
    # counts the failed policy read, then re-raises it unchanged
    ("services/api_gateway/studio_policy_reads.py", "CountedPolicyReads.fetch"): [
        "bookkeeping-reraise"
    ],
    # any transport failure, which may carry the client secret, becomes a redacted StudioTokenError
    ("services/api_gateway/studio_runtime_token.py", "StudioRuntimeTokenProvider._refresh"): [
        "fallback"
    ],
    # telemetry and metrics must never change a refinement outcome
    ("services/api_gateway/translation_refiner.py", "BaseTranslationRefiner._emit_attempt"): [
        "boundary",
        "boundary",
    ],
    # the unrefined translation
    (
        "services/api_gateway/translation_refiner.py",
        "OllamaTranslationRefiner._perform_refinement",
    ): ["fallback"],
    # answers the JSON 500, then re-raises redacted
    ("services/api_gateway/unhandled_errors.py", "UnhandledErrorMiddleware.__call__"): [
        "bookkeeping-reraise"
    ],
    # a failed close still releases the connection
    ("services/api_gateway/websocket.py", "WebSocketManager.disconnect_websocket"): ["boundary"],
    # a failed ack must not leak the registered connection
    ("services/api_gateway/websocket.py", "WebSocketManager._send_connection_ack"): ["boundary"],
    # a failed notice must not skip the close
    ("services/api_gateway/websocket.py", "WebSocketManager._send_disconnect_message"): [
        "boundary"
    ],
    # a failed send still releases the connection
    ("services/api_gateway/websocket.py", "WebSocketManager._disconnect_connection_with_message"): [
        "boundary"
    ],
    # per message, the error-frame send, and the socket's outer edge
    ("services/api_gateway/websocket.py", "websocket_endpoint"): [
        "boundary",
        "boundary",
        "boundary",
    ],
    # one failed cleanup pass must not end the loop
    ("services/api_gateway/websocket_monitor.py", "WebSocketMonitor.periodic_cleanup"): [
        "boundary"
    ],
    # the service starts degraded and /transcribe answers 500
    ("services/asr/app.py", "_load_asr_model"): ["fallback"],
    # the endpoint's edge: a structured 500 with the type logged
    ("services/asr/app.py", "transcribe"): ["boundary"],
    # health without NVML figures
    ("services/gpu_metrics.py", "_initialize_nvml"): ["fallback"],
    # health without one device's NVML or torch figures
    ("services/gpu_metrics.py", "_collect_device_metrics"): ["fallback", "fallback"],
    # per-request stats without psutil figures
    ("services/resource_metrics.py", "get_system_stats"): ["fallback"],
    # health without psutil figures
    ("services/resource_metrics.py", "collect_resource_metrics"): ["fallback"],
    # the service starts degraded and /translate answers 503
    ("services/translation/app.py", "<module>"): ["fallback"],
    # the endpoint's edge: a counted, structured 500
    ("services/translation/app.py", "translate"): ["boundary"],
    # one broken voice must not stop the others loading
    ("services/tts/app.py", "load_speakers"): ["boundary"],
    # the endpoint's edge: a structured 500 with the type logged
    ("services/tts/app.py", "synthesize"): ["boundary"],
    # no VRAM figure rather than a broken /health
    ("services/tts/vram.py", "ProcessVram.read"): ["fallback"],
}


def _is_broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in BROAD
    if isinstance(node, ast.Attribute):
        return node.attr in BROAD
    if isinstance(node, ast.Tuple):
        return any(_is_broad(element) for element in node.elts)
    return False


SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
SKIPPED_DIRECTORIES = {"tests", "node_modules", "__pycache__", "frontend", ".venv"}


def _collect(node: ast.AST, scope: list[str], path: str, found: dict[tuple[str, str], int]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES):
            _collect(child, [*scope, child.name], path, found)
            continue
        if isinstance(child, ast.ExceptHandler) and _is_broad(child.type):
            key = (path, ".".join(scope) or "<module>")
            found[key] = found.get(key, 0) + 1
        _collect(child, scope, path, found)


def _production_modules(root: Path) -> list[Path]:
    modules = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(d for d in subdirectories if d not in SKIPPED_DIRECTORIES)
        modules.extend(Path(directory, name) for name in sorted(files) if name.endswith(".py"))
    return modules


def broad_handlers(root: Path = SERVICES) -> dict[tuple[str, str], int]:
    found: dict[tuple[str, str], int] = {}
    for path in _production_modules(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _collect(tree, [], path.relative_to(ROOT).as_posix(), found)
    return found


def test_every_broad_handler_is_listed_with_one_reason_each():
    found = broad_handlers()

    unlisted = sorted(key for key in found if key not in ALLOWED)
    miscounted = sorted(
        (key, found[key], len(ALLOWED[key]))
        for key in found
        if key in ALLOWED and found[key] != len(ALLOWED[key])
    )
    assert unlisted == [], f"broad handler without a reason: {unlisted}"
    assert miscounted == [], f"handler count differs from its reasons: {miscounted}"


def test_no_listed_handler_has_gone():
    found = broad_handlers()

    stale = sorted(key for key in ALLOWED if key not in found)
    assert stale == [], f"listed but no longer present: {stale}"


def test_every_reason_is_one_of_the_three():
    unknown = sorted(
        (key, reason)
        for key, reasons in ALLOWED.items()
        for reason in reasons
        if reason not in REASONS
    )
    assert unknown == []
