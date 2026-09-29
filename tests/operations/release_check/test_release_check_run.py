from scripts.release_check.__main__ import run
from scripts.release_check.config import load_settings
from scripts.release_check.evidence import Evidence
from scripts.release_check.login import LoginError
from tests.operations.release_check.release_check_fakes import FakeGateway
from tests.operations.release_check.test_release_check_config import _environment


async def _login(tenant, operator):
    return f"token-{tenant.label}{operator.username[-1]}"


def _settings(**overrides):
    return load_settings(_environment(**overrides))


def _failed(evidence: Evidence) -> list[str]:
    return [check.name for check in evidence.checks if not check.passed]


async def test_a_healthy_run_passes_and_keeps_only_consented_content():
    gateway, evidence = FakeGateway(), Evidence()

    assert await run(_settings(), gateway, evidence, _login) is True
    assert _failed(evidence) == []
    names = [check.name for check in evidence.checks]
    assert "A1 keeps 4 messages" in names
    assert "A2 keeps 0 messages" in names
    assert "B1 audio 1 answers 200" in names
    assert "B2 audio 1 answers 404" in names


async def test_refused_content_that_survives_termination_fails():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.keep_refused_content = True

    assert await run(_settings(), gateway, evidence, _login) is False
    assert "A2 keeps 0 messages" in _failed(evidence)


async def test_a_disabled_tenant_keeps_nothing_even_with_consent():
    gateway, evidence = FakeGateway(storage={"A": "ask", "B": "disabled"}), Evidence()

    assert await run(_settings(SSF_RC_TENANT_B_STORAGE="disabled"), gateway, evidence, _login)
    assert "B1 keeps 0 messages" in [check.name for check in evidence.checks]


async def test_cleanup_terminates_every_session_after_a_failure(monkeypatch):
    monkeypatch.setattr("scripts.release_check.scenario.DELIVERY_TIMEOUT", 0.05)
    gateway, evidence = FakeGateway(), Evidence()
    gateway.drop_delivery = True

    assert await run(_settings(), gateway, evidence, _login) is False
    assert sorted(gateway.terminated) == sorted(gateway.sessions)
    assert "isolation skipped" in _failed(evidence)


async def test_a_failed_login_creates_nothing():
    gateway, evidence = FakeGateway(), Evidence()

    async def refuse(tenant, operator):
        raise LoginError("Keycloak rejected the credentials")

    assert await run(_settings(), gateway, evidence, refuse) is False
    assert gateway.sessions == {}


async def test_the_report_carries_no_token_password_or_session_id():
    gateway, evidence = FakeGateway(), Evidence()
    settings = _settings()
    for secret in settings.secrets():
        evidence.add_secret(secret)

    await run(settings, gateway, evidence, _login)
    rendered = evidence.to_markdown() + evidence.to_json()

    for forbidden in ("token-A1", "secret-A1", *gateway.sessions):
        assert forbidden not in rendered
