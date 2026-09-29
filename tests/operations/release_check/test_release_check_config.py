import pytest

from scripts.release_check.config import ConfigError, load_settings


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "SSF_RC_API_BASE": "https://api.example/",
        "SSF_RC_KEYCLOAK_BASE": "https://auth.example",
        "SSF_RC_FRONTEND_ORIGIN": "https://app.example",
        "SSF_RC_TENANT_A_ID": "tenant-a",
        "SSF_RC_TENANT_B_ID": "tenant-b",
    }
    for label in ("A", "B"):
        for n in (1, 2):
            values[f"SSF_RC_TENANT_{label}_USER_{n}"] = f"user-{label}{n}"
            values[f"SSF_RC_TENANT_{label}_PASSWORD_{n}"] = f"secret-{label}{n}"
    values.update(overrides)
    return values


def test_reads_both_tenants_with_defaults():
    settings = load_settings(_environment())

    assert settings.api_base == "https://api.example"
    assert settings.client_id == "ssf-frontend"
    first, second = settings.tenants
    assert (first.label, first.directory_id, first.guest_language, first.storage_mode) == (
        "A",
        "tenant-a",
        "en",
        "ask",
    )
    assert (second.guest_language, second.storage_mode) == ("tr", "ask")
    assert [op.username for op in second.operators] == ["user-B1", "user-B2"]


def test_derives_websocket_base_and_callback():
    secure = load_settings(_environment())
    plain = load_settings(_environment(SSF_RC_API_BASE="http://localhost:8000"))

    assert secure.websocket_base == "wss://api.example"
    assert plain.websocket_base == "ws://localhost:8000"
    assert secure.redirect_uri(secure.tenants[0]) == "https://app.example/login/tenant-a"


def test_names_a_missing_variable():
    environment = _environment()
    del environment["SSF_RC_TENANT_B_PASSWORD_2"]

    with pytest.raises(ConfigError, match="SSF_RC_TENANT_B_PASSWORD_2 is not set"):
        load_settings(environment)


def test_never_echoes_an_invalid_value():
    with pytest.raises(ConfigError) as raised:
        load_settings(_environment(SSF_RC_TENANT_A_STORAGE="hunter2"))

    assert "SSF_RC_TENANT_A_STORAGE" in str(raised.value)
    assert "hunter2" not in str(raised.value)


def test_rejects_the_same_tenant_twice():
    with pytest.raises(ConfigError, match="must differ"):
        load_settings(_environment(SSF_RC_TENANT_B_ID="tenant-a"))


def test_keeps_passwords_out_of_repr_and_lists_them_as_secrets():
    settings = load_settings(_environment())

    assert "secret-A1" not in repr(settings)
    assert sorted(settings.secrets()) == ["secret-A1", "secret-A2", "secret-B1", "secret-B2"]
