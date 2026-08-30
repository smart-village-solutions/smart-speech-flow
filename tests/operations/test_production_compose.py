from pathlib import Path

import yaml


COMPOSE_PATH = Path("deploy/production/docker-compose.production.yml")


def load_production_compose():
    return yaml.safe_load(COMPOSE_PATH.read_text())


def test_production_compose_contains_the_running_workload():
    services = load_production_compose()["services"]
    required = {
        "api_gateway",
        "asr",
        "translation",
        "tts",
        "ollama",
        "redis",
        "clickhouse",
        "keycloak",
        "keycloak-postgres",
        "traefik",
        "prometheus",
        "grafana",
        "loki",
        "promtail",
        "dcgm_exporter",
        "cadvisor",
        "node_exporter",
        "frontend",
        "frontend-archive",
    }
    assert required.issubset(services)


def test_production_compose_forbids_builds_and_mutable_image_tags():
    services = load_production_compose()["services"]
    for name, service in services.items():
        assert "build" not in service, name
        image = service["image"]
        assert ":latest" not in image, name
        assert "@sha256:" in image or ":prod-" in image, name


def test_production_services_restart_automatically():
    for name, service in load_production_compose()["services"].items():
        assert service.get("restart") == "unless-stopped", name
