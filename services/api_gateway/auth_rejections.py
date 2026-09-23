"""Closed, token-safe reason codes for rejected administrative bearer tokens.

The client always receives the same neutral body. The reason exists only in the
server log and the counter, so a tenant whose tokens cannot pass is diagnosable
without decoding a token by hand (#363).
"""

import json
import logging
from enum import StrEnum
from uuid import uuid4

from fastapi import HTTPException, status
from prometheus_client import CollectorRegistry, Counter
from starlette.requests import HTTPConnection

from .correlation_id import is_valid_correlation_id
from .session_pseudonym import tenant_ref

logger = logging.getLogger(__name__)


class AuthRejectionReason(StrEnum):
    MISSING_BEARER = "missing_bearer"
    MALFORMED_TOKEN = "malformed_token"
    GATEWAY_AUTH_MISCONFIGURED = "gateway_auth_misconfigured"
    DIRECTORY_UNAVAILABLE = "directory_unavailable"
    UNKNOWN_ISSUER = "unknown_issuer"
    UNSUPPORTED_TOKEN_HEADER = "unsupported_token_header"
    SIGNING_KEYS_UNAVAILABLE = "signing_keys_unavailable"
    UNKNOWN_SIGNING_KEY = "unknown_signing_key"
    INVALID_SIGNING_KEY = "invalid_signing_key"
    TOKEN_EXPIRED = "token_expired"
    INVALID_AUDIENCE = "invalid_audience"
    INVALID_ISSUER = "invalid_issuer"
    INVALID_SIGNATURE = "invalid_signature"
    MISSING_REQUIRED_CLAIM = "missing_required_claim"
    INVALID_TOKEN = "invalid_token"
    TENANT_CLAIM_MISMATCH = "tenant_claim_mismatch"
    REVISION_MISSING = "revision_missing"
    REVISION_MALFORMED = "revision_malformed"
    ROLE_MISSING = "role_missing"
    LEGACY_TENANT_CLAIM = "legacy_tenant_claim"


def rejection_status(reason: AuthRejectionReason) -> int:
    if reason is AuthRejectionReason.DIRECTORY_UNAVAILABLE:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if reason is AuthRejectionReason.ROLE_MISSING:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_401_UNAUTHORIZED


def rejection_response(reason: AuthRejectionReason) -> HTTPException:
    """The client-facing error, identical for every 401 reason."""
    code = rejection_status(reason)
    if code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return HTTPException(
            status_code=code, detail="The login directory is temporarily unavailable"
        )
    if code == status.HTTP_403_FORBIDDEN:
        return HTTPException(status_code=code, detail="The bearer token lacks the required role")
    return HTTPException(
        status_code=code,
        detail="A valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def auth_correlation_id(connection: HTTPConnection) -> str:
    """Return the caller's correlation ID when valid, otherwise a new one.

    Unlike `correlation_id_from_request`, this never raises: a malformed header
    must not turn an authentication failure into a 400.
    """
    supplied = connection.headers.get("X-Correlation-Id", "")
    return supplied if is_valid_correlation_id(supplied) else str(uuid4())


class AuthRejectionMetrics:
    """Rejected administrative tokens by reason, on the gateway's registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._rejections = Counter(
            "gateway_auth_rejections_total",
            "Administrative bearer tokens rejected by the gateway, by reason",
            ["reason"],
            registry=registry,
        )
        for reason in AuthRejectionReason:
            self._rejections.labels(reason=reason.value).inc(0)

    def record(self, reason: AuthRejectionReason) -> None:
        self._rejections.labels(reason=reason.value).inc()


def record_auth_rejection(
    connection: HTTPConnection,
    reason: AuthRejectionReason,
    *,
    correlation_id: str,
    tenant_id: str | None = None,
) -> None:
    """Log one rejection and count it, never logging token contents."""
    fields = {
        "reason": reason.value,
        "status": rejection_status(reason),
        "tenant_ref": tenant_ref(tenant_id) if tenant_id else "-",
        "correlation_id": correlation_id,
    }
    # The caller chooses the correlation ID, which may contain spaces and "=":
    # it is JSON-quoted so it cannot forge a key=value field.
    logger.log(
        # No bearer at all is ordinary anonymous traffic, not a failed token.
        logging.INFO if reason is AuthRejectionReason.MISSING_BEARER else logging.WARNING,
        "ssf_auth_rejected reason=%s status=%s tenant_ref=%s correlation_id=%s",
        fields["reason"],
        fields["status"],
        fields["tenant_ref"],
        json.dumps(correlation_id),
        extra=fields,
    )
    metrics = getattr(connection.app.state, "auth_rejection_metrics", None)
    if metrics is not None:
        metrics.record(reason)
