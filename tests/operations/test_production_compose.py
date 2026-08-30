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


def test_production_compose_preserves_the_existing_prometheus_volume():
    compose = load_production_compose()
    prometheus = compose["services"]["prometheus"]
    assert "prometheus-data:/prometheus" in prometheus["volumes"]
    assert compose["volumes"]["prometheus-data"]["external"] is True


def test_keycloak_realm_mount_resolves_to_the_versioned_file():
    keycloak = load_production_compose()["services"]["keycloak"]
    realm_mount = next(
        volume
        for volume in keycloak["volumes"]
        if volume.endswith(":/opt/keycloak/data/import/ssf-realm.json:ro")
    )
    source = Path(realm_mount.split(":", maxsplit=1)[0])

    assert source == Path("deploy/production/keycloak/ssf-realm.json")
    assert source.is_file()


def test_recovery_unit_never_recreates_existing_containers():
    unit = Path("deploy/systemd/ssf-production.service").read_text()
    assert "up --detach --no-build --pull never --no-recreate" in unit
    assert "Restart=on-failure" in unit
