import json
import stat

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
    assert "B1 audio retrievable during conversation" in names
    assert "B2 serves no audio after termination" in names
    assert "A1 → A2 status is not found" in names
    assert "B2 → B1 terminate is not found" in names


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


# A tester session left live by an earlier run would be ended by this one.
async def test_a_testers_leftover_conversation_stops_the_run_before_anything_is_created():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.seed_live_session("B", owner="token-B2")

    assert await run(_settings(), gateway, evidence, _login) is False
    assert list(gateway.sessions) == ["real-B"]
    assert gateway.terminated == []
    assert _failed(evidence) == ["B2 has no live conversation"]


# The gateway shows no admin a colleague's conversation (#476), and a run ends
# only the testers' own (#473), so a real user's conversation neither stops the
# run nor is touched by it.
async def test_a_real_users_conversation_is_invisible_and_untouched():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.seed_live_session("A")

    assert await run(_settings(), gateway, evidence, _login) is True
    assert gateway.sessions["real-A"].status == "active"
    assert "real-A" not in gateway.terminated


async def test_an_unreadable_history_stops_the_run():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.history_status = 503

    assert await run(_settings(), gateway, evidence, _login) is False
    assert gateway.sessions == {}
    assert "A1 has no live conversation" in _failed(evidence)


async def test_an_idle_tenant_pair_passes_the_preflight():
    gateway, evidence = FakeGateway(), Evidence()

    await run(_settings(), gateway, evidence, _login)

    names = [check.name for check in evidence.checks if check.passed]
    assert {f"{label} has no live conversation" for label in ("A1", "A2", "B1", "B2")} <= set(names)


async def test_audio_served_after_termination_fails():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.serve_audio_after_termination = True

    assert await run(_settings(), gateway, evidence, _login) is False
    assert "A1 serves no audio after termination" in _failed(evidence)


async def test_audio_missing_during_the_conversation_fails():
    gateway, evidence = FakeGateway(), Evidence()
    gateway.missing_live_audio = True

    assert await run(_settings(), gateway, evidence, _login) is False
    assert "A1 audio retrievable during conversation" in _failed(evidence)


# The on-host audio retention check needs the session ids the report hides.
async def test_the_manifest_is_owner_only_and_names_each_conversation(tmp_path):
    gateway, evidence = FakeGateway(), Evidence()
    manifest = tmp_path / "manifest.json"

    await run(_settings(), gateway, evidence, _login, manifest=manifest)

    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    entries = json.loads(manifest.read_text())["conversations"]
    assert [(e["label"], e["consent"], e["storage"]) for e in entries] == [
        ("A1", True, "ask"),
        ("A2", False, "ask"),
        ("B1", True, "ask"),
        ("B2", False, "ask"),
    ]
    assert {e["session_id"] for e in entries} == set(gateway.sessions)
    assert all(len(e["message_ids"]) == 4 for e in entries)


async def test_no_manifest_is_written_unless_asked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    await run(_settings(), FakeGateway(), Evidence(), _login)

    assert list(tmp_path.iterdir()) == []
