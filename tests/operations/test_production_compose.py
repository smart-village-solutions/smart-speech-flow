from pathlib import Path

import yaml


COMPOSE_PATH = Path("deploy/production/docker-compose.production.yml")
ENV_EXAMPLE_PATH = Path("deploy/production/production.env.example")
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


def _load_env_example():
    return {
        line.split("=", maxsplit=1)[0]: line.split("=", maxsplit=1)[1]
        for line in ENV_EXAMPLE_PATH.read_text().splitlines()
        if line and not line.startswith("#")
    }


def test_production_gateway_uses_studio_backed_multi_realm_configuration():
    gateway = load_production_compose()["services"]["api_gateway"]
    environment = _environment_by_name(gateway)

    assert environment["KEYCLOAK_BASE_URL"] == (
        "${KEYCLOAK_BASE_URL:-https://auth.dialog.kassel.de}"
    )
    assert environment["KEYCLOAK_AUDIENCE"] == "${KEYCLOAK_AUDIENCE:-ssf-frontend}"
    assert environment["KEYCLOAK_REQUIRED_ROLE"] == "${KEYCLOAK_REQUIRED_ROLE:-ssf-user}"
    assert environment["STUDIO_RUNTIME_CONFIGURATION_BASE_URL"] == (
        "${STUDIO_RUNTIME_CONFIGURATION_BASE_URL:-https://studio.dialog.kassel.de}"
    )
    assert environment["STUDIO_RUNTIME_TOKEN_URL"] == "${STUDIO_RUNTIME_TOKEN_URL:?required}"
    assert environment["STUDIO_RUNTIME_CLIENT_ID"] == "${STUDIO_RUNTIME_CLIENT_ID:-ssf-runtime}"
    assert environment["STUDIO_RUNTIME_AUDIENCE"] == (
        "${STUDIO_RUNTIME_AUDIENCE:-sva-studio-ssf-runtime}"
    )
    assert environment["STUDIO_RUNTIME_CLIENT_SECRET"] == (
        "${STUDIO_RUNTIME_CLIENT_SECRET:?required}"
    )
    assert environment["STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS"] == (
        "${STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS:-60}"
    )
    assert "KEYCLOAK_ISSUER" not in environment


def test_production_gateway_uses_the_approved_tenant_timeout_and_cutover_values():
    gateway = load_production_compose()["services"]["api_gateway"]
    environment = _environment_by_name(gateway)

    assert environment["SSF_ENABLE_LEGACY_ADMIN_ACCESS"] == "false"
    assert environment["SSF_SESSION_RECONNECT_GRACE_MINUTES"] == "30"
    assert environment["SSF_SESSION_TIMEOUT_WARNING_MINUTES"] == "5"
    assert environment["SSF_SESSION_MAX_HOURS"] == "8"


def test_production_routes_match_the_trusted_frontend_and_keycloak_origins():
    services = load_production_compose()["services"]
    gateway_environment = _environment_by_name(services["api_gateway"])
    keycloak = services["keycloak"]

    assert gateway_environment["CLIENT_BASE_URL"] == "https://dialog.kassel.de"
    assert gateway_environment["KEYCLOAK_BASE_URL"] == (
        "${KEYCLOAK_BASE_URL:-https://auth.dialog.kassel.de}"
    )
    assert keycloak["environment"]["KC_HOSTNAME"] == (
        "https://auth.dialog.kassel.de"
    )
    assert (
        "traefik.http.routers.keycloak.rule=Host(`auth.dialog.kassel.de`)"
        in keycloak["labels"]
    )
    assert (
        "traefik.http.routers.frontend.rule=Host(`dialog.kassel.de`)"
        in services["frontend"]["labels"]
    )


def test_production_example_documents_tenant_login_configuration_without_secrets():
    environment = _load_env_example()

    assert environment["KEYCLOAK_BASE_URL"] == "https://auth.dialog.kassel.de"
    assert environment["KEYCLOAK_AUDIENCE"] == "ssf-frontend"
    assert environment["KEYCLOAK_REQUIRED_ROLE"] == "ssf-user"
    assert environment["STUDIO_RUNTIME_CONFIGURATION_BASE_URL"] == (
        "https://studio.dialog.kassel.de"
    )
    assert environment["STUDIO_RUNTIME_CLIENT_ID"] == "ssf-runtime"
    assert environment["STUDIO_RUNTIME_AUDIENCE"] == "sva-studio-ssf-runtime"
    assert environment["STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS"] == "60"
    assert environment["STUDIO_RUNTIME_CLIENT_SECRET"] == ""
    assert "STUDIO_RUNTIME_TOKEN_URL" in environment
    assert "KEYCLOAK_ISSUER" not in environment


def test_production_keycloak_does_not_import_the_development_realm():
    keycloak = load_production_compose()["services"]["keycloak"]

    assert "--import-realm" not in keycloak["command"]
    assert all(
        "/opt/keycloak/data/import" not in volume
        for volume in keycloak.get("volumes", [])
    )


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
