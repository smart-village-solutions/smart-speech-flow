import importlib
import os

import pytest


# Module namespaces as they were before this test reloaded them.
_RELOADED: dict[str, dict[str, object]] = {}


@pytest.fixture(autouse=True)
def restore_reloaded_modules():
    """Put every reloaded module back as it was once the test ends.

    A reload leaves new classes and import-time constants behind. Later tests
    then build apps from classes they never imported and patched, as
    test_gateway_app_isolation.py does, or find a different `app`.
    """
    yield
    for module_path, namespace in _RELOADED.items():
        module = importlib.import_module(module_path)
        module.__dict__.clear()
        module.__dict__.update(namespace)
    _RELOADED.clear()


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
        _RELOADED.setdefault(module_path, dict(module.__dict__))
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
    assert app_module.SERVICE_URLS["ASR"] == "http://asr:8000/health"
    assert app_module._build_service_url("asr", 8000, "/transcribe", scheme="http") == (
        "http://asr:8000/transcribe"
    )
    assert app_module._localhost_origin(3000, secure=True) == "https://localhost:3000"

    app_module = reload_module(
        "services.api_gateway.app",
        {
            "DOCKER_COMPOSE": "0",
            "SERVICE_SCHEME": "http",
            "LOCAL_SERVICE_SCHEME": "https",
        },
    )
    assert app_module.SERVICE_URLS["TTS"] == "https://localhost:8003/health"
    assert (
        app_module._build_service_url("localhost", 8003, "/synthesize", scheme="https")
        == "https://localhost:8003/synthesize"
    )


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
    monkeypatch.setenv("DEVELOPMENT_CORS_ORIGINS", "https://example.test,http://devbox:3000")

    app_module.setup_cors_for_websockets(app_module.app)

    allow_origins = captured["kwargs"]["allow_origins"]
    assert "https://example.test" in allow_origins
    assert "http://devbox:3000" in allow_origins
    assert app_module._localhost_origin(3000) in allow_origins
    assert app_module._localhost_origin(3000, secure=True) in allow_origins
    assert captured["kwargs"]["allow_origin_regex"] is None


def _speech_services(env: dict[str, str | None]):
    """The speech adapter with its URLs resolved under ``env``, on its own breakers."""
    from services.api_gateway.service_health import ServiceHealthManager

    module = reload_module("services.api_gateway.speech_services", env)
    return module, module.HttpSpeechServices(ServiceHealthManager().circuit_breakers)


def test_speech_service_urls_use_the_local_scheme_outside_compose():
    speech_services, _ = _speech_services(
        {
            "DOCKER_COMPOSE": "0",
            "SERVICE_SCHEME": "http",
            "LOCAL_SERVICE_SCHEME": "https",
        },
    )
    assert speech_services.ASR_URL == "https://localhost:8001/transcribe"


def test_translation_refiner_default_endpoint_and_enabled_configuration():
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LLM_REFINEMENT_SCHEME", "https")
        env.setenv("LLM_REFINEMENT_HOST", "llm")
        env.setenv("LLM_REFINEMENT_PORT", "443")
        assert (
            reload_module(
                "services.api_gateway.translation_refiner",
                {"LLM_REFINEMENT_ENABLED": "0"},
            )._default_refinement_endpoint("ollama")
            == "https://llm:443"
        )

    module = importlib.import_module("services.api_gateway.translation_refiner")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LLM_REFINEMENT_ENABLED", "1")
        env.delenv("LLM_REFINEMENT_ENDPOINT", raising=False)
        env.setenv("LLM_REFINEMENT_SCHEME", "https")
        env.setenv("LLM_REFINEMENT_HOST", "llm")
        env.setenv("LLM_REFINEMENT_PORT", "443")
        refiner = module.get_translation_refiner()
    assert refiner.is_active is True
    assert refiner.endpoint == "https://llm:443"


def test_service_health_helpers_use_configured_scheme():
    service_health = reload_module(
        "services.api_gateway.service_health",
        {"SERVICE_SCHEME": "https"},
    )
    manager = service_health.ServiceHealthManager()
    assert service_health._service_base_url("asr") == "https://asr:8000"
    assert manager.services["asr"].base_url == "https://asr:8000"
    assert manager.services["translation"].base_url == "https://translation:8000"
    assert manager.services["tts"].base_url == "https://tts:8000"


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


def test_primary_refinement_status_distinguishes_skip_from_success():
    """A refinement skipped by the language policy has no error, so
    `"error" if outcome.error else "success"` used to record it as a success
    with a 0 ms duration, dragging benchmark latency figures down and hiding
    the skip. `skipped_reason` must produce its own status."""
    pipeline_logic = importlib.import_module("services.api_gateway.pipeline_logic")

    success = pipeline_logic.RefinementOutcome(text="hallo", changed=False, latency_ms=250.0)
    skipped = pipeline_logic.RefinementOutcome(
        text="hallo", changed=False, latency_ms=0.0, skipped_reason="unsupported_target_language"
    )
    errored = pipeline_logic.RefinementOutcome(
        text="hallo", changed=False, latency_ms=10.0, error="timeout"
    )

    assert pipeline_logic._primary_refinement_status(success) == "success"
    assert pipeline_logic._primary_refinement_status(skipped) == "skipped"
    assert pipeline_logic._primary_refinement_status(errored) == "error"
