import json

from scripts.release_check.evidence import Evidence, session_ref
from scripts.release_check.steps import run_step


def test_passes_only_when_every_check_passed():
    evidence = Evidence()
    assert not evidence.passed

    evidence.record("one", True)
    assert evidence.passed

    evidence.record("two", False, "HTTP 500")
    assert not evidence.passed


# Secrets are registered after the checks that might mention them (a token is
# only known once login succeeds), so redaction must apply at rendering time.
def test_redacts_secrets_registered_after_recording():
    evidence = Evidence()
    evidence.record("login", True, "token eyJ-token-value, password pw-123, text Guten Tag")
    for secret in ("eyJ-token-value", "pw-123", "Guten Tag"):
        evidence.add_secret(secret)

    rendered = evidence.to_markdown() + evidence.to_json()

    for secret in ("eyJ-token-value", "pw-123", "Guten Tag"):
        assert secret not in rendered
    assert "[redacted]" in rendered


def test_session_ref_is_a_stable_short_hash():
    reference = session_ref("A1B2C3D4")

    assert reference == session_ref("A1B2C3D4")
    assert len(reference) == 12
    assert "A1B2C3D4" not in reference


def test_markdown_escapes_table_separators():
    evidence = Evidence()
    evidence.record("a|b", True, "x|y")

    assert "a\\|b" in evidence.to_markdown()
    assert "x\\|y" in evidence.to_markdown()


def test_json_report_lists_every_check():
    evidence = Evidence()
    evidence.record("one", True, "ok", 12)

    report = json.loads(evidence.to_json())

    assert report == {
        "passed": True,
        "checks": [{"name": "one", "passed": True, "detail": "ok", "duration_ms": 12}],
    }


async def test_run_step_records_a_failure_for_a_transport_error():
    evidence = Evidence()

    async def broken() -> tuple[bool, str]:
        raise ConnectionError("refused")

    assert await run_step(evidence, "step", broken) is False
    assert evidence.checks[0].passed is False
    assert evidence.checks[0].detail == "ConnectionError"
