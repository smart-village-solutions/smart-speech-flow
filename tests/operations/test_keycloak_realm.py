import json
from pathlib import Path


REALM_PATH = Path("deploy/production/keycloak/ssf-realm.json")


def test_ssf_realm_provisions_a_public_pkce_client_for_the_frontend():
    realm = json.loads(REALM_PATH.read_text())

    assert realm["realm"] == "ssf"
    client = next(client for client in realm["clients"] if client["clientId"] == "ssf-frontend")
    assert client["publicClient"] is True
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
