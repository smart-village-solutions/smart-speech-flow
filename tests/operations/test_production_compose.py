from pathlib import Path

import yaml


COMPOSE_PATH = Path("deploy/production/docker-compose.production.yml")
DEVELOPMENT_COMPOSE_PATH = Path("docker-compose.yml")


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


def test_pinned_legacy_application_images_keep_the_legacy_auth_contract():
    services = load_production_compose()["services"]
    gateway = services["api_gateway"]
    frontend = services["frontend"]
    environment = _environment_by_name(gateway)

    legacy_application_images_are_pinned = (
        gateway["image"] == "ssf-backend-api_gateway:prod-c3c69e9"
        or frontend["image"] == "ssf-backend-frontend:prod-d4d1feb"
    )

    if legacy_application_images_are_pinned:
        assert environment["KEYCLOAK_ISSUER"] == (
            "${KEYCLOAK_ISSUER:-https://auth.kassel.smartspeechflow.de/realms/ssf}"
        )
        assert "KEYCLOAK_BASE_URL" not in environment
        assert "STUDIO_RUNTIME_CONFIGURATION_BASE_URL" not in environment


def test_production_services_restart_automatically():
    for name, service in load_production_compose()["services"].items():
        assert service.get("restart") == "unless-stopped", name


def test_production_compose_preserves_the_existing_prometheus_volume():
    compose = load_production_compose()
    prometheus = compose["services"]["prometheus"]
    assert "prometheus-data:/prometheus" in prometheus["volumes"]
    assert compose["volumes"]["prometheus-data"]["external"] is True


def _environment_by_name(service):
    return {
        entry.split("=", maxsplit=1)[0]: entry.split("=", maxsplit=1)[1]
        for entry in service["environment"]
    }


def test_keycloak_realm_mount_resolves_to_the_versioned_file():
    keycloak = load_production_compose()["services"]["keycloak"]
    realm_mount = next(
        volume
        for volume in keycloak["volumes"]
        if volume.endswith(":/opt/keycloak/data/import/ssf-realm.json:ro")
    )
    source = (COMPOSE_PATH.parent / realm_mount.split(":", maxsplit=1)[0]).resolve()
    expected_source = Path("deploy/production/keycloak/ssf-realm.json").resolve()

    assert source == expected_source
    assert source.is_file()


def test_frontend_build_receives_public_multi_realm_configuration():
    compose = yaml.safe_load(DEVELOPMENT_COMPOSE_PATH.read_text())
    build_args = compose["services"]["frontend"]["build"]["args"]

    assert build_args["VITE_KEYCLOAK_URL"] == "https://auth.dialog.kassel.de"
    assert build_args["VITE_KEYCLOAK_CLIENT_ID"] == "ssf-frontend"
    assert "VITE_KEYCLOAK_REALM" not in build_args


def test_recovery_unit_relies_on_docker_restart_policies_without_compose_reconciliation():
    unit = Path("deploy/systemd/ssf-production.service").read_text()
    assert "ExecStart=/usr/bin/true" in unit
    assert "docker compose" not in unit
    assert "ExecStop=" not in unit
    assert "ExecStartPost=/root/projects/ssf-backend/scripts/production-health-check.sh --timeout-seconds 300" in unit
    assert "Restart=on-failure" in unit
