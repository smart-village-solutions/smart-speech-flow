from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"


def _traefik() -> dict[str, object]:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return compose["services"]["traefik"]


def test_traefik_watches_the_dynamic_configuration_directory() -> None:
    traefik = _traefik()

    assert "--providers.file.directory=/etc/traefik/dynamic" in traefik["command"]
    assert "--providers.file.watch=true" in traefik["command"]
    assert "./traefik/dynamic:/etc/traefik/dynamic:ro" in traefik["volumes"]


def test_dynamic_provider_preserves_existing_security_boundaries() -> None:
    traefik = _traefik()

    assert "--providers.docker=true" in traefik["command"]
    assert "--providers.docker.exposedbydefault=false" in traefik["command"]
    assert "--certificatesresolvers.le.acme.tlschallenge=true" in traefik["command"]
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in traefik["volumes"]
    assert "./letsencrypt:/letsencrypt" in traefik["volumes"]

