import logging
from hashlib import sha256

import pytest

from services.api_gateway.session_access import log_tenant_access_denied
from services.api_gateway.session_manager import SessionManager
from services.api_gateway.session_pseudonym import session_ref
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


def test_cross_tenant_denial_log_contains_only_pseudonymous_references(caplog):
    key = TenantSessionKey("secret-tenant", "ABC12345")

    with caplog.at_level(logging.INFO):
        log_tenant_access_denied(key, outcome="not_found")

    assert "secret-tenant" not in caplog.text
    assert "ABC12345" not in caplog.text
    assert sha256(b"secret-tenant").hexdigest()[:12] in caplog.text
    assert "tenant_session_access_denied" in caplog.text


def test_security_log_rejects_unbounded_outcomes(caplog):
    key = TenantSessionKey("secret-tenant", "ABC12345")

    with caplog.at_level(logging.INFO):
        log_tenant_access_denied(key, outcome="private details from the caller")

    assert "private details from the caller" not in caplog.text
    assert "invalid" in caplog.text


@pytest.mark.asyncio
async def test_customer_activation_logs_only_pseudonymous_session_scope(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager = SessionManager(
        store=MemoryTenantSessionStore(),
        session_id_factory=lambda: "JOIN1234",
    )
    session = await manager.create_admin_session("secret-tenant", SNAPSHOT)
    capsys.readouterr()

    with caplog.at_level(logging.INFO):
        await manager.activate_session(session.key, "en")

    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert "secret-tenant" not in output
    assert "JOIN1234" not in output
    assert sha256(b"secret-tenant").hexdigest()[:12] in caplog.text
    assert session_ref("JOIN1234") in caplog.text
    assert "tenant_session_activation" in caplog.text
