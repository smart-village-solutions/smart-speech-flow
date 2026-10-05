"""Regression tests for the Keycloak Compose security contract."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
KEYCLOAK_DOCKERFILE = ROOT / "services/keycloak/Dockerfile"


def _keycloak_services(compose: dict) -> tuple[dict, dict]:
    services = compose["services"]
    return services["keycloak"], services["keycloak-postgres"]


def test_keycloak_is_public_only_through_traefik(rendered_development_compose: dict) -> None:
    """Fail if Keycloak loses its canonical TLS route or gets a host port."""
    keycloak, _ = _keycloak_services(rendered_development_compose)

    assert keycloak["image"] == "ssf-keycloak:26.7.2"
    assert keycloak["restart"] == "always"
    assert keycloak.get("ports") is None
    assert keycloak["expose"] == ["8080"]
    assert keycloak["labels"]["traefik.http.routers.keycloak.rule"] == "Host(`auth.test.example`)"
    assert keycloak["environment"]["KC_HOSTNAME"] == "https://auth.test.example"
    assert keycloak["environment"]["KC_PROXY_HEADERS"] == "xforwarded"
    assert keycloak["healthcheck"]


def test_keycloak_postgres_is_private_persistent_and_credentialed(rendered_development_compose: dict) -> None:
    """Fail if the identity database becomes public or loses durable state."""
    keycloak, postgres = _keycloak_services(rendered_development_compose)

    assert postgres["image"] == "postgres:17.7-alpine"
    assert postgres["restart"] == "always"
    assert postgres.get("ports") is None
    assert postgres.get("expose") is None
    assert postgres.get("labels") is None
    assert postgres["healthcheck"]
    assert {
        "type": "volume",
        "source": "keycloak-postgres-data",
        "target": "/var/lib/postgresql/data",
        "volume": {},
    } in postgres["volumes"]
    assert postgres["environment"] == {
        "POSTGRES_DB": "keycloak_test",
        "POSTGRES_USER": "keycloak_test_user",
        "POSTGRES_PASSWORD": "test-only-db-password",
    }
    assert keycloak["environment"]["KC_DB"] == "postgres"
    assert keycloak["environment"]["KC_DB_URL_HOST"] == "keycloak-postgres"
    assert keycloak["environment"]["KC_DB_URL_DATABASE"] == "keycloak_test"
    assert keycloak["environment"]["KC_DB_USERNAME"] == "keycloak_test_user"
    assert keycloak["environment"]["KC_DB_PASSWORD"] == "test-only-db-password"
    assert keycloak["environment"]["KC_BOOTSTRAP_ADMIN_USERNAME"] == "bootstrap_admin"
    assert keycloak["environment"]["KC_BOOTSTRAP_ADMIN_PASSWORD"] == "test-only-admin-password"


def test_keycloak_runbook_uses_the_configured_hostname_and_preserves_private_ports() -> None:
    """Keep operational instructions aligned with the Compose security boundary."""
    runbook = (ROOT / "docs/operations/runbooks/keycloak-operations.md").read_text()

    assert "KEYCLOAK_HOSTNAME" in runbook
    assert "management port 9000" in runbook


def test_keycloak_runtime_image_explicitly_uses_the_unprivileged_image_user() -> None:
    """Make the final Keycloak image's runtime identity unambiguous to scanners."""
    final_stage = KEYCLOAK_DOCKERFILE.read_text().split(
        "FROM quay.io/keycloak/keycloak:26.7.2\n", 1
    )[1]

    assert "USER 1000" in final_stage
