from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE_PATH = ROOT / "deploy" / "production" / "docker-compose.production.yml"


def _traefik() -> dict[str, object]:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return compose["services"]["traefik"]


def _production_traefik() -> dict[str, object]:
    compose = yaml.safe_load(PRODUCTION_COMPOSE_PATH.read_text(encoding="utf-8"))
    return compose["services"]["traefik"]


def test_traefik_watches_the_dynamic_configuration_directory() -> None:
    traefik = _traefik()

    assert "--providers.file.directory=/etc/traefik/dynamic" in traefik["command"]
    assert "--providers.file.watch=true" in traefik["command"]
    assert "./traefik/dynamic:/etc/traefik/dynamic:ro" in traefik["volumes"]


def test_production_traefik_watches_the_dynamic_configuration_directory() -> None:
    traefik = _production_traefik()

    assert "--providers.file.directory=/etc/traefik/dynamic" in traefik["command"]
    assert "--providers.file.watch=true" in traefik["command"]
    assert "../../traefik/dynamic:/etc/traefik/dynamic:ro" in traefik["volumes"]


def test_dynamic_provider_preserves_existing_security_boundaries() -> None:
    development = _traefik()
    production = _production_traefik()

    for traefik in (development, production):
        assert "--providers.docker=true" in traefik["command"]
        assert "--providers.docker.exposedbydefault=false" in traefik["command"]
        assert "--certificatesresolvers.le.acme.tlschallenge=true" in traefik["command"]
        assert "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json" in traefik["command"]
        assert "/var/run/docker.sock:/var/run/docker.sock:ro" in traefik["volumes"]

    assert "./letsencrypt:/letsencrypt" in development["volumes"]
    assert "../../letsencrypt:/letsencrypt" in production["volumes"]
