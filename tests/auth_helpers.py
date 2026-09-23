"""Shared authenticated principals for suites that override the auth dependencies."""

from services.api_gateway.auth import AuthenticatedPrincipal

REVISION = "sha256:" + "a" * 64


def principal(
    tenant_id: str = "tenant-test",
    subject: str | None = "test-admin",
    *,
    carries_legacy_tenant_claim: bool = False,
) -> AuthenticatedPrincipal:
    """A principal as `require_ssf_user` would build it for `tenant_id`'s realm."""
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        realm=f"{tenant_id}-realm",
        authorization_revision=REVISION,
        subject=subject,
        carries_legacy_tenant_claim=carries_legacy_tenant_claim,
    )
