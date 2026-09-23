import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from tests.script_helpers import load_contract


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


def _realm():
    return json.loads(DEVELOPMENT_REALM_PATH.read_text())


def _client(realm):
    return next(client for client in realm["clients"] if client["clientId"] == "ssf-frontend")


def _drop_mappers(value):
    """Remove every mapper that emits `value` as a claim or an audience."""

    def mutate(realm):
        client = _client(realm)
        client["protocolMappers"] = [
            mapper
            for mapper in client["protocolMappers"]
            if value
            not in (
                mapper["config"].get("claim.name"),
                mapper["config"].get("included.client.audience"),
            )
        ]

    return mutate


def _add_tenant_id_mapper(realm):
    _client(realm)["protocolMappers"].append(
        {
            "name": "studio-studio-tenant-id",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {"claim.name": "studio_tenant_id", "access.token.claim": "true"},
        }
    )


def test_realm_artifact_satisfies_the_gateway_contract():
    realm = _realm()

    assert realm["realm"] == "ssf"
    assert load_contract().missing_realm_elements(realm) == []
    assert "users" not in realm
    assert "translate.smart-village.solutions" not in json.dumps(realm)
    assert _client(realm)["redirectUris"] == ["https://dialog.kassel.de/login/*"]
    assert _client(realm)["webOrigins"] == ["https://dialog.kassel.de"]


@pytest.mark.parametrize(
    ("element", "mutate"),
    [
        ("public-pkce-client", lambda realm: _client(realm).update(publicClient=False)),
        ("public-pkce-client", lambda realm: _client(realm).update(secret="x")),
        (
            "public-pkce-client",
            lambda realm: _client(realm)["attributes"].pop("pkce.code.challenge.method"),
        ),
        ("public-pkce-client", lambda realm: _client(realm).update(implicitFlowEnabled=True)),
        (
            "public-pkce-client",
            lambda realm: _client(realm).update(directAccessGrantsEnabled=True),
        ),
        ("public-pkce-client", lambda realm: _client(realm).update(standardFlowEnabled=False)),
        (
            "login-redirects",
            lambda realm: _client(realm).update(redirectUris=["https://dialog.kassel.de/*"]),
        ),
        (
            "login-redirects",
            lambda realm: _client(realm).update(redirectUris=["http://dialog.kassel.de/login/*"]),
        ),
        ("login-redirects", lambda realm: _client(realm).update(redirectUris=[])),
        ("audience-mapper", _drop_mappers("ssf-frontend")),
        ("revision-mapper", _drop_mappers("ssf_authorization_revision")),
        ("ssf-user-role", lambda realm: realm["roles"].update(realm=[])),
        ("no-tenant-id-mapper", _add_tenant_id_mapper),
    ],
)
def test_the_contract_names_each_broken_element(element, mutate):
    realm = _realm()
    mutate(realm)
    assert load_contract().missing_realm_elements(realm) == [element]


@pytest.mark.parametrize(
    ("value", "element"),
    [("ssf_authorization_revision", "revision-mapper"), ("ssf-frontend", "audience-mapper")],
)
def test_a_mapper_that_skips_the_access_token_does_not_count(value, element):
    realm = _realm()
    for mapper in _client(realm)["protocolMappers"]:
        if value in (
            mapper["config"].get("claim.name"),
            mapper["config"].get("included.client.audience"),
        ):
            mapper["config"]["access.token.claim"] = "false"
    assert load_contract().missing_realm_elements(realm) == [element]


def test_a_missing_client_fails_every_client_element():
    realm = _realm()
    realm["clients"] = []
    assert load_contract().missing_realm_elements(realm) == [
        "public-pkce-client",
        "login-redirects",
        "audience-mapper",
        "revision-mapper",
    ]


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
        assert b"max-width: 800px;" in stylesheet
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
