import re
from pathlib import Path

import yaml


COMPOSE_PATH = Path("deploy/production/docker-compose.production.yml")
ENV_EXAMPLE_PATH = Path("deploy/production/production.env.example")
DEVELOPMENT_COMPOSE_PATH = Path("docker-compose.yml")

# translation_refiner.py's get_translation_refiner() resolves
# LLM_REFINEMENT_PRIMARY_MODEL before falling back to LLM_REFINEMENT_MODEL.
# The vllm service's --served-model-name must read the same variable, or an
# operator who sets only one of them gets a gateway that requests a model
# name vLLM never advertised under, and every refinement 404s.
GATEWAY_MODEL_VARIABLE = "LLM_REFINEMENT_PRIMARY_MODEL"


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


def test_vllm_is_gated_behind_a_profile_in_both_compose_files():
    """A routine deploy brings up all services with no service filter, so an
    ungated vllm would start on every deploy -- either failing to pull (its
    image is not yet on the host) or silently booting a GPU-reserving
    container before its first boot has been measured by hand."""
    for path in (DEVELOPMENT_COMPOSE_PATH, COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text())
        vllm = compose["services"]["vllm"]
        assert vllm["profiles"] == ["vllm"], path


def _served_model_variable(vllm_service):
    for arg in vllm_service["command"]:
        if arg.startswith("--served-model-name="):
            match = re.search(r"\$\{(\w+)", arg)
            assert match, f"could not parse a variable out of {arg!r}"
            return match.group(1)
    raise AssertionError("vllm command has no --served-model-name")


def test_vllm_served_model_name_uses_the_same_variable_the_gateway_resolves_first():
    for path in (DEVELOPMENT_COMPOSE_PATH, COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text())
        environment = _environment_by_name(compose["services"]["api_gateway"])
        assert GATEWAY_MODEL_VARIABLE in environment, path

        vllm = compose["services"]["vllm"]
        assert _served_model_variable(vllm) == GATEWAY_MODEL_VARIABLE, path


def test_skip_target_languages_default_is_reachable_with_an_explicitly_empty_value():
    """`${VAR:-default}` also substitutes the default for an explicitly empty
    value, so the documented "empty refines everything" behaviour would be
    unreachable through compose. `${VAR-default}` (no colon) only substitutes
    when the variable is unset, so an empty value set by an operator survives."""
    for path in (DEVELOPMENT_COMPOSE_PATH, COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text())
        environment = _environment_by_name(compose["services"]["api_gateway"])
        assert environment["LLM_REFINEMENT_SKIP_TARGET_LANGUAGES"] == (
            "${LLM_REFINEMENT_SKIP_TARGET_LANGUAGES-am,ti,ku,fa}"
        ), path


def test_vllm_boots_the_measured_quantized_model_with_no_ram_offload():
    """Production measurement (2026-09-23) chose Qwen/Qwen3.5-4B at
    --quantization fp8 and --gpu-memory-utilization 0.40 (weights 5.09 GiB,
    peak activation 1.36 GiB, KV cache 1.16 GiB, 5.3 GiB free). The Gemma
    build at 0.58 unquantized was measured and rejected: negative room for
    KV cache. --cpu-offload-gb=0 must be explicit so the model never spills
    into system RAM."""
    for path in (DEVELOPMENT_COMPOSE_PATH, COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text())
        command = compose["services"]["vllm"]["command"]
        assert "--model=${LLM_REFINEMENT_MODEL_REPO:-Qwen/Qwen3.5-4B}" in command, path
        assert "--quantization=${VLLM_QUANTIZATION:-fp8}" in command, path
        assert "--gpu-memory-utilization=${VLLM_GPU_MEMORY_UTILIZATION:-0.40}" in command, path
        assert "--cpu-offload-gb=0" in command, path


def test_refinement_temperature_defaults_to_deterministic_output():
    """Measured (2026-09-23): at 0.7, refining a real German-to-English
    sentence invented an instruction in two of three runs; at 0.0, three of
    three preserved the meaning exactly. This is a deliberate change for the
    Ollama path too, not just vllm."""
    for path in (DEVELOPMENT_COMPOSE_PATH, COMPOSE_PATH):
        compose = yaml.safe_load(path.read_text())
        environment = _environment_by_name(compose["services"]["api_gateway"])
        assert environment["LLM_REFINEMENT_TEMPERATURE"] == (
            "${LLM_REFINEMENT_TEMPERATURE:-0.0}"
        ), path


def test_development_gateway_can_exercise_the_vllm_path():
    """The dev stack's gateway environment previously never passed
    LLM_REFINEMENT_BACKEND, LLM_REFINEMENT_MAX_TOKENS or
    LLM_REFINEMENT_SKIP_TARGET_LANGUAGES, so it could never be pointed at
    the vllm backend the way production can."""
    compose = yaml.safe_load(DEVELOPMENT_COMPOSE_PATH.read_text())
    environment = _environment_by_name(compose["services"]["api_gateway"])
    assert environment["LLM_REFINEMENT_BACKEND"] == "${LLM_REFINEMENT_BACKEND:-ollama}"
    assert environment["LLM_REFINEMENT_MAX_TOKENS"] == "${LLM_REFINEMENT_MAX_TOKENS:-256}"
    assert environment["LLM_REFINEMENT_SKIP_TARGET_LANGUAGES"] == (
        "${LLM_REFINEMENT_SKIP_TARGET_LANGUAGES-am,ti,ku,fa}"
    )


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

    assert "SSF_ENABLE_LEGACY_ADMIN_ACCESS" not in environment
    assert "SSF_LEGACY_ADMIN_ACCESS_CODE" not in environment
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


def test_recovery_unit_reconciles_with_the_guarded_production_deploy_script():
    unit = Path("deploy/systemd/ssf-production.service").read_text()
    assert (
        "ExecStart=/root/projects/ssf-backend/scripts/deploy-production.sh --apply"
        in unit
    )
    assert "ExecStart=/usr/bin/true" not in unit
    assert "docker compose" not in unit
    assert "TimeoutStartSec=360" in unit
    assert "ExecStop=" not in unit
    assert "ExecStartPost=/root/projects/ssf-backend/scripts/production-health-check.sh --timeout-seconds 300" in unit
    assert "Restart=on-failure" in unit
