import importlib
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def reload_module(module_path: str, env: dict[str, str | None]):
    saved: dict[str, str | None] = {}
    for key, value in env.items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    try:
        module = importlib.import_module(module_path)
        return importlib.reload(module)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_app_module_builds_service_urls_for_docker_and_local():
    app_module = reload_module(
        "services.api_gateway.app",
        {
            "DOCKER_COMPOSE": "1",
            "SERVICE_SCHEME": "http",
            "LOCAL_SERVICE_SCHEME": None,
        },
    )
    assert app_module.ASR_URL == "http://asr:8000/transcribe"
    assert app_module.TRANSLATION_URL == "http://translation:8000/translate"
    assert app_module.TTS_URL == "http://tts:8000/synthesize"
    assert app_module.SERVICE_URLS["ASR"] == "http://asr:8000/health"
    assert app_module._localhost_origin(3000, secure=True) == "https://localhost:3000"

    app_module = reload_module(
        "services.api_gateway.app",
        {
            "DOCKER_COMPOSE": "0",
            "SERVICE_SCHEME": "http",
            "LOCAL_SERVICE_SCHEME": "https",
        },
    )
    assert app_module.ASR_URL == "https://localhost:8001/transcribe"
    assert app_module.TRANSLATION_URL == "https://localhost:8002/translate"
    assert app_module.TTS_URL == "https://localhost:8003/synthesize"
    assert app_module.SERVICE_URLS["TTS"] == "https://localhost:8003/health"


def test_app_cors_setup_uses_localhost_helpers_in_development(monkeypatch):
    app_module = reload_module(
        "services.api_gateway.app",
        {
            "DOCKER_COMPOSE": "0",
            "ENVIRONMENT": "production",
            "DEVELOPMENT_CORS_ORIGINS": "",
        },
    )
    captured = {}

    def fake_add_middleware(middleware, **kwargs):  # noqa: ANN001
        captured["middleware"] = middleware
        captured["kwargs"] = kwargs

    monkeypatch.setattr(app_module.app, "add_middleware", fake_add_middleware)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(
        "DEVELOPMENT_CORS_ORIGINS", "https://example.test,http://devbox:3000"
    )

    app_module.setup_cors_for_websockets()

    allow_origins = captured["kwargs"]["allow_origins"]
    assert "https://example.test" in allow_origins
    assert "http://devbox:3000" in allow_origins
    assert app_module._localhost_origin(3000) in allow_origins
    assert app_module._localhost_origin(3000, secure=True) in allow_origins
    assert captured["kwargs"]["allow_origin_regex"] is None


def test_pipeline_logic_helpers_cover_refinement_and_tts_paths(monkeypatch):
    pipeline_logic = reload_module(
        "services.api_gateway.pipeline_logic",
        {
            "DOCKER_COMPOSE": "0",
            "SERVICE_SCHEME": "http",
            "LOCAL_SERVICE_SCHEME": "https",
        },
    )
    assert pipeline_logic.ASR_URL == "https://localhost:8001/transcribe"

    debug_info = {"steps": []}
    mock_refiner = SimpleNamespace(
        is_active=True,
        refine=Mock(
            return_value=pipeline_logic.RefinementOutcome(
                text="refined",
                changed=True,
                latency_ms=250.0,
                error=None,
            )
        ),
    )
    monkeypatch.setattr(pipeline_logic, "translation_refiner", mock_refiner)

    refined_text, refined_tts_text = pipeline_logic._apply_translation_refinement(
        processed_text="hello",
        translation_text="hallo",
        source_lang="en",
        target_lang="de",
        debug_info=debug_info,
        tts_text="romanized",
    )
    assert refined_text == "refined"
    assert refined_tts_text is None
    assert debug_info["steps"][-1]["name"] == "refinement"

    captured = {}

    def fake_post(url, json, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(status_code=200, content=b"audio", headers={})

    monkeypatch.setattr(pipeline_logic.requests, "post", fake_post)
    response, duration_ms, *_ = pipeline_logic._run_text_tts_step(
        translation_text="refined",
        target_lang="de",
        session_id="session-1",
        debug=True,
        refined_tts_text="tts-ready",
    )
    assert response.status_code == 200
    assert duration_ms >= 0
    assert captured["url"] == "https://localhost:8003/synthesize"
    assert captured["json"]["tts_text"] == "tts-ready"

    debug_info = {"steps": []}
    pipeline_logic._append_tts_debug_step(
        debug_info=debug_info,
        target_lang="de",
        translation_text="refined",
        error_msg="tts failed",
        tts_duration_ms=5,
        tts_started_at=pipeline_logic.utc_now(),
        tts_completed_at=pipeline_logic.utc_now(),
        start_tts=0.0,
    )
    assert debug_info["steps"][-1]["error"] == "tts failed"


def test_pipeline_logic_translation_helper_records_debug_step(monkeypatch):
    pipeline_logic = reload_module(
        "services.api_gateway.pipeline_logic",
        {
            "DOCKER_COMPOSE": "1",
            "SERVICE_SCHEME": "https",
            "LOCAL_SERVICE_SCHEME": None,
        },
    )
    debug_info = {"steps": []}

    def fake_post(url, json, timeout):  # noqa: ANN001
        assert url == "https://translation:8000/translate"
        assert json["source_lang"] == "en"
        assert json["target_lang"] == "de"
        assert timeout == 30
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"translations": "Hallo", "tts_text": "Hallo"},
        )

    monkeypatch.setattr(pipeline_logic.requests, "post", fake_post)

    response, payload, translation_text, tts_text = (
        pipeline_logic._run_text_translation_step(
            processed_text="Hello",
            source_lang="en",
            target_lang="de",
            debug=True,
            debug_info=debug_info,
        )
    )

    assert response.status_code == 200
    assert payload["translations"] == "Hallo"
    assert translation_text == "Hallo"
    assert tts_text == "Hallo"
    assert debug_info["steps"][-1]["name"] == "translation"


def test_process_text_pipeline_covers_tts_error_and_success_paths(monkeypatch):
    pipeline_logic = importlib.import_module("services.api_gateway.pipeline_logic")

    monkeypatch.setattr(
        pipeline_logic,
        "_validate_and_normalize_text",
        lambda text, debug_info, start_total: ("Hello", None),
    )
    monkeypatch.setattr(
        pipeline_logic,
        "_run_text_translation_step",
        lambda **kwargs: (
            SimpleNamespace(status_code=200),
            {"translations": "Hallo"},
            "Hallo",
            "Hallo",
        ),
    )
    monkeypatch.setattr(
        pipeline_logic,
        "_apply_translation_refinement",
        lambda **kwargs: ("Hallo", None),
    )

    error_response = SimpleNamespace(
        status_code=500,
        headers={"content-type": "application/json"},
        json=lambda: {"error": "tts kaputt"},
        text="kaputt",
    )
    monkeypatch.setattr(
        pipeline_logic,
        "_run_text_tts_step",
        lambda **kwargs: (
            error_response,
            3,
            pipeline_logic.utc_now(),
            pipeline_logic.utc_now(),
            0.0,
        ),
    )
    error_result = pipeline_logic.process_text_pipeline(
        "Hello", "en", "de", session_id="s1", debug=True
    )
    assert error_result["error"] is True
    assert error_result["translation_text"] == "Hallo"
    assert error_result["error_msg"] == "TTS-Fehler: tts kaputt"

    success_response = SimpleNamespace(
        status_code=200,
        headers={"content-type": pipeline_logic.AUDIO_WAV_MIME},
        content=b"WAV",
    )
    monkeypatch.setattr(
        pipeline_logic,
        "_run_text_tts_step",
        lambda **kwargs: (
            success_response,
            5,
            pipeline_logic.utc_now(),
            pipeline_logic.utc_now(),
            0.0,
        ),
    )
    success_result = pipeline_logic.process_text_pipeline(
        "Hello", "en", "tr", session_id="s2", debug=True
    )
    assert success_result["error"] is False
    assert success_result["audio_bytes"] == b"WAV"
    assert success_result["debug"]["steps"][-1]["model"] == "tts_models/tr/common-voice/glow-tts"
    assert success_result["debug"]["steps"][-1]["language"] == "tr"


@pytest.mark.asyncio
async def test_routes_session_activity_helper_and_endpoint(monkeypatch):
    session_routes = importlib.import_module("services.api_gateway.routes.session")

    connection_one = SimpleNamespace(current_polling_interval=5)
    connection_two = SimpleNamespace(current_polling_interval=15)
    manager = SimpleNamespace(
        session_connections={"session-1": {"a": connection_one, "b": connection_two}},
        adaptive_polling=SimpleNamespace(
            update_client_status=Mock(side_effect=[10, 15]),
            get_battery_optimization_tips=Mock(side_effect=[["tip-a"], ["tip-b"]]),
        ),
        _send_polling_interval_update=AsyncMock(),
        get_session_connections=Mock(return_value=[{"id": "a"}, {"id": "b"}]),
    )
    activity = session_routes.ClientActivityUpdate(
        is_mobile=True,
        tab_active=False,
        battery_level=0.2,
        network_quality="slow",
    )

    new_intervals, tips = await session_routes._apply_activity_update_to_session_connections(
        manager, "session-1", activity
    )
    assert new_intervals == [10, 15]
    assert sorted(tips) == ["tip-a", "tip-b"]
    manager._send_polling_interval_update.assert_awaited_once_with(
        connection_one, 10, reason="client_activity_update"
    )

    active_session = SimpleNamespace(
        status=session_routes.SessionStatus.ACTIVE,
        id="session-1",
    )
    monkeypatch.setattr(
        session_routes.session_manager, "get_session", lambda session_id: active_session
    )
    update_activity = Mock()
    monkeypatch.setattr(session_routes.session_manager, "update_session_activity", update_activity)
    manager.adaptive_polling.update_client_status = Mock(side_effect=[10, 15])
    manager.adaptive_polling.get_battery_optimization_tips = Mock(
        side_effect=[["tip-a"], ["tip-b"]]
    )
    manager._send_polling_interval_update = AsyncMock()

    response = await session_routes.update_client_activity("session-1", activity, manager)
    assert response.status == "success"
    assert response.new_polling_interval == 12
    assert sorted(response.optimization_tips) == ["tip-a", "tip-b"]
    update_activity.assert_called_once_with("session-1")


def test_legacy_session_routes_expose_documented_responses():
    legacy_session = importlib.import_module("services.api_gateway.session")
    route_map = {
        route.path: route
        for route in legacy_session.router.routes
        if hasattr(route, "responses")
    }

    assert route_map["/session/create"].responses[400]["description"] == (
        "Unsupported customer language"
    )
    assert route_map["/session/{session_id}"].responses[404]["description"] == (
        legacy_session.SESSION_NOT_FOUND_DETAIL
    )
    assert route_map["/session/{session_id}/message"].responses[500]["description"] == (
        "Message processing failed"
    )
    assert route_map["/session/{session_id}/messages"].responses[404]["description"] == (
        legacy_session.SESSION_NOT_FOUND_DETAIL
    )


@pytest.mark.asyncio
async def test_websocket_polling_routes_wait_and_poll(monkeypatch):
    polling_routes = importlib.import_module("services.api_gateway.websocket_polling_routes")

    messages = [{"type": "message"}]
    poll = Mock(side_effect=[[], messages])
    monkeypatch.setattr(polling_routes.fallback_manager, "poll_messages", poll)
    monkeypatch.setattr(polling_routes.asyncio, "sleep", AsyncMock())
    if not hasattr(polling_routes.asyncio, "timeout"):
        async def passthrough(awaitable, timeout):  # noqa: ANN001
            return await awaitable

        monkeypatch.setattr(polling_routes.asyncio, "wait_for", passthrough)

    waited = await polling_routes._await_polled_messages("poll-1", 1)
    assert waited == messages

    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "get_polling_client_status",
        lambda polling_id: {"polling_interval": 7},
    )
    poll = Mock(side_effect=[[], messages])
    monkeypatch.setattr(polling_routes.fallback_manager, "poll_messages", poll)
    response = await polling_routes.poll_messages("poll-1", timeout=1)
    payload = json.loads(response.body)
    assert payload["messages"] == messages
    assert payload["next_poll_interval"] == 7


@pytest.mark.asyncio
async def test_websocket_polling_routes_timeout_returns_empty_list(monkeypatch):
    polling_routes = importlib.import_module("services.api_gateway.websocket_polling_routes")

    if hasattr(polling_routes.asyncio, "timeout"):
        class TimeoutContext:
            async def __aenter__(self):
                raise TimeoutError()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(
            polling_routes.asyncio, "timeout", lambda seconds: TimeoutContext()
        )
    else:
        async def raise_timeout(awaitable, timeout):  # noqa: ANN001
            awaitable.close()
            raise polling_routes.asyncio.TimeoutError()

        monkeypatch.setattr(polling_routes.asyncio, "wait_for", raise_timeout)

    assert await polling_routes._await_polled_messages("poll-2", 1) == []


def test_translation_refiner_default_endpoint_and_enabled_configuration():
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LLM_REFINEMENT_SCHEME", "https")
        env.setenv("LLM_REFINEMENT_HOST", "llm")
        env.setenv("LLM_REFINEMENT_PORT", "443")
        assert (
            reload_module(
                "services.api_gateway.translation_refiner",
                {"LLM_REFINEMENT_ENABLED": "0"},
            )._default_refinement_endpoint()
            == "https://llm:443"
        )

    module = reload_module(
        "services.api_gateway.translation_refiner",
        {
            "LLM_REFINEMENT_ENABLED": "1",
            "LLM_REFINEMENT_ENDPOINT": None,
            "LLM_REFINEMENT_SCHEME": "https",
            "LLM_REFINEMENT_HOST": "llm",
            "LLM_REFINEMENT_PORT": "443",
        },
    )
    assert module.translation_refiner.is_active is True
    assert module.translation_refiner.endpoint == "https://llm:443"

    reload_module("services.api_gateway.translation_refiner", {"LLM_REFINEMENT_ENABLED": "0"})


def test_service_health_and_circuit_breaker_helpers_use_configured_scheme():
    service_health = reload_module(
        "services.api_gateway.service_health",
        {"SERVICE_SCHEME": "https"},
    )
    manager = service_health.ServiceHealthManager()
    assert service_health._service_base_url("asr") == "https://asr:8000"
    assert manager.services["asr"].base_url == "https://asr:8000"
    assert manager.services["translation"].base_url == "https://translation:8000"
    assert manager.services["tts"].base_url == "https://tts:8000"

    client_module = reload_module(
        "services.api_gateway.circuit_breaker_client",
        {"SERVICE_SCHEME": "https"},
    )
    assert client_module._service_url("asr", "/transcribe") == "https://asr:8000/transcribe"
    assert client_module._service_url("translation", "/translate") == (
        "https://translation:8000/translate"
    )
    assert client_module._service_url("tts", "/synthesize") == "https://tts:8000/synthesize"


@pytest.mark.asyncio
async def test_websocket_origin_prefixes_allow_localhost_in_development(monkeypatch):
    websocket = importlib.import_module("services.api_gateway.websocket")
    assert websocket._localhost_origin_prefixes() == (
        "http://localhost",
        "https://localhost",
    )

    monkeypatch.setenv("ENVIRONMENT", "development")
    assert await websocket.validate_websocket_origin("http://localhost:5173") is True
    assert await websocket.validate_websocket_origin(None) is True
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert await websocket.validate_websocket_origin(None) is False


@pytest.mark.asyncio
async def test_legacy_pipeline_route_returns_success_and_error_payloads(monkeypatch):
    pipeline_route = importlib.import_module("services.api_gateway.routes.pipeline")

    class UploadStub:
        async def read(self):
            return b"wav-bytes"

    request = SimpleNamespace(
        query_params={},
        headers={"origin": "https://translate.smart-village.solutions"},
    )

    monkeypatch.setattr(
        pipeline_route,
        "process_wav",
        lambda *args, **kwargs: {
            "error": False,
            "asr_text": "hello",
            "translation_text": "hallo",
            "audio_bytes": b"audio",
            "debug": {"ok": True},
        },
    )
    success = await pipeline_route.pipeline(
        request=request,
        file=UploadStub(),
        source_lang="en",
        target_lang="de",
        debug="true",
    )
    success_payload = json.loads(success.body)
    assert success.status_code == 200
    assert success_payload["success"] is True
    assert success_payload["audioBase64"] is not None

    monkeypatch.setattr(
        pipeline_route,
        "process_wav",
        lambda *args, **kwargs: {
            "error": True,
            "error_msg": "bad audio",
            "debug": {"ok": False},
        },
    )
    failure = await pipeline_route.pipeline(
        request=request,
        file=UploadStub(),
        source_lang="en",
        target_lang="de",
    )
    failure_payload = json.loads(failure.body)
    assert failure.status_code == 400
    assert failure_payload["success"] is False
    assert failure_payload["error"] == "bad audio"
