import json
from pathlib import Path

import yaml


DEVELOPMENT_REALM_PATH = Path("deploy/production/keycloak/ssf-realm.json")
DEVELOPMENT_COMPOSE_PATH = Path("docker-compose.yml")


def test_development_compose_imports_only_the_local_realm_fixture():
    keycloak = yaml.safe_load(DEVELOPMENT_COMPOSE_PATH.read_text())["services"][
        "keycloak"
    ]

    assert "--import-realm" in keycloak["command"]
    assert keycloak["volumes"] == [
        "./deploy/production/keycloak/ssf-realm.json:/opt/keycloak/data/import/ssf-realm.json:ro"
    ]


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
