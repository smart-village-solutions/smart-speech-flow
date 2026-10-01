"""Where the speech services are reached: Docker service names, or localhost ports outside Compose."""

import os

# === Service-URLs für die Orchestrierung ===
# Je nach Umgebung werden interne Docker- oder lokale URLs verwendet
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"
DEFAULT_INTERNAL_SCHEME = os.environ.get("SERVICE_SCHEME", "http")
DEFAULT_LOCAL_SCHEME = os.environ.get("LOCAL_SERVICE_SCHEME", DEFAULT_INTERNAL_SCHEME)
HEALTH_PATH = "/health"


def _build_service_base_url(host: str, port: int, *, scheme: str) -> str:
    return f"{scheme}://{host}:{port}"


def _build_service_url(host: str, port: int, path: str, *, scheme: str) -> str:
    return f"{_build_service_base_url(host, port, scheme=scheme)}{path}"


if DOCKER_ENV:
    # Docker-Service-URLs für Microservices
    SERVICE_URLS = {
        "ASR": _build_service_url("asr", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME),
        "Translation": _build_service_url(
            "translation", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME
        ),
        "TTS": _build_service_url("tts", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME),
    }
else:
    # Lokale Service-URLs für Entwicklung ohne Docker
    SERVICE_URLS = {
        "ASR": _build_service_url("localhost", 8001, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME),
        "Translation": _build_service_url(
            "localhost", 8002, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME
        ),
        "TTS": _build_service_url("localhost", 8003, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME),
    }
