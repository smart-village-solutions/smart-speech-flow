import logging
from hashlib import sha256

from services.api_gateway.session_access import log_tenant_access_denied
from services.api_gateway.tenant_session import TenantSessionKey


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
