import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


DEVELOPMENT_REALM_PATH = Path("deploy/production/keycloak/ssf-realm.json")
DEVELOPMENT_COMPOSE_PATH = Path("docker-compose.yml")
DOCKERIGNORE_PATH = Path(".dockerignore")
KEYCLOAK_DOCKERFILE = Path("services/keycloak/Dockerfile")
FRONTEND_ASSETS = Path("services/frontend/public/assets")


def _theme_file(image: str, relative_path: str) -> bytes:
    container_id = subprocess.check_output(
        ["docker", "create", image], text=True
    ).strip()
    destination = Path(tempfile.mkdtemp())
    try:
        subprocess.run(
            [
                "docker",
                "cp",
                f"{container_id}:/opt/keycloak/themes/kasseldialog/login/{relative_path}",
                destination,
            ],
            check=True,
        )
        return (destination / Path(relative_path).name).read_bytes()
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], check=True)
        shutil.rmtree(destination)


def test_development_compose_imports_only_the_local_realm_fixture():
    keycloak = yaml.safe_load(DEVELOPMENT_COMPOSE_PATH.read_text())["services"][
        "keycloak"
    ]

    assert keycloak["build"] == {"context": ".", "dockerfile": "services/keycloak/Dockerfile"}
    assert "--import-realm" in keycloak["command"]
    assert keycloak["volumes"] == [
        "./deploy/production/keycloak/ssf-realm.json:/opt/keycloak/data/import/ssf-realm.json:ro"
    ]


def test_keycloak_build_context_excludes_local_secret_files():
    """The root build context must not upload ignored deployment credentials."""
    ignored_paths = set(DOCKERIGNORE_PATH.read_text().splitlines())

    assert {".env", ".env.*", "deploy/production/production.env"} <= ignored_paths


def test_development_realm_provisions_a_secretless_public_pkce_client():
    realm = json.loads(DEVELOPMENT_REALM_PATH.read_text())

    assert realm["realm"] == "ssf"
    client = next(client for client in realm["clients"] if client["clientId"] == "ssf-frontend")
    assert client["publicClient"] is True
    assert "secret" not in client
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"] == [
        "https://translate.smart-village.solutions/",
        "https://translate.smart-village.solutions/login",
    ]
    assert client["webOrigins"] == ["https://translate.smart-village.solutions"]
    assert any(
        mapper["protocolMapper"] == "oidc-audience-mapper"
        and mapper["config"]["included.client.audience"] == "ssf-frontend"
        and mapper["config"]["access.token.claim"] == "true"
        for mapper in client["protocolMappers"]
    )
    assert {role["name"] for role in realm["roles"]["realm"]} >= {"ssf-user"}


@pytest.mark.integration
def test_keycloak_image_provides_the_kasseldialog_login_branding():
    """The shipped Keycloak image must carry the frontend's approved branding."""
    image = "ssf-keycloak-kasseldialog-theme-test"
    subprocess.run(
        ["docker", "build", "--file", str(KEYCLOAK_DOCKERFILE), "--tag", image, "."],
        check=True,
    )

    try:
        theme_properties = _theme_file(image, "theme.properties")
        assert b"parent=keycloak" in theme_properties
        assert b"styles=css/login.css" in theme_properties
        assert _theme_file(image, "resources/img/header-logo.png") == (
            FRONTEND_ASSETS / "Logo.png"
        ).read_bytes()
        assert _theme_file(image, "resources/img/footer-funding.png") == (
            FRONTEND_ASSETS / "Foerdermittelgeber.png"
        ).read_bytes()
        assert _theme_file(image, "resources/img/footer-city.png") == (
            FRONTEND_ASSETS / "Stadt.png"
        ).read_bytes()
        assert _theme_file(image, "resources/fonts/Inter-Variable.woff2") == (
            Path("services/frontend/public/fonts/Inter-Variable.woff2")
        ).read_bytes()
        stylesheet = _theme_file(image, "resources/css/login.css")
        assert b"html.login-pf,\nhtml.login-pf body" in stylesheet
        assert b"background-image: none" in stylesheet
        assert (
            b".login-pf-page {\n  width: 100%;\n  margin: 0;\n  padding-top: 0;\n}"
            in stylesheet
        )
        assert b"background-position: center top;" in stylesheet
        assert b".login-pf-page > .card-pf" in stylesheet
        assert b"--footer-content-width: calc(100% - 40px);" in stylesheet
        assert b"--footer-logo-gap: 16px;" in stylesheet
        assert b"@media (min-width: 640px)" in stylesheet
        assert b"--footer-content-width: min(calc(100% - 64px), 736px);" in stylesheet
        assert b"--footer-logo-gap: 48px;" in stylesheet
        assert b"@media (min-width: 1024px)" in stylesheet
        assert b"--footer-content-width: min(calc(100% - 96px), 704px);" in stylesheet
        assert b"--footer-logo-gap: 112px;" in stylesheet
        assert b"calc(50% - var(--footer-logo-offset))" in stylesheet
        assert b"calc(50% + var(--footer-logo-offset))" in stylesheet
        assert (
            b"calc((var(--footer-content-width) - var(--footer-logo-gap)) / 2)"
            in stylesheet
        )
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False)


def test_development_realm_selects_the_kasseldialog_login_theme():
    """The development login flow must render the bundled KasselDIALOG theme."""
    realm = json.loads(DEVELOPMENT_REALM_PATH.read_text())

    assert realm["loginTheme"] == "kasseldialog"
