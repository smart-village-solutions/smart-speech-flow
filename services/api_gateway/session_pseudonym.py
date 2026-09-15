"""Keyed, one-way session references for telemetry.

The gateway already reduces session ids to ``sha256(session_id)[:12]`` in four
places before logging them. That is adequate for a log line and inadequate
here: session ids are 32-bit, so an unkeyed digest of one can be reversed by
enumerating the input space, and telemetry rows live for 30 days in a store
built to be joined and grouped. An HMAC keyed by a deployment secret closes
that, because the id space cannot be enumerated without the key.

Scope is deliberately narrow: this is the telemetry pipeline's pseudonymiser,
not a replacement for the four logging helpers. Converging those is a separate
change, since it alters what appears in existing operational logs.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Final

logger = logging.getLogger(__name__)

SESSION_KEY_ENV: Final[str] = "SSF_QUALITY_TELEMETRY_SESSION_KEY"

# 128 bits of a SHA-256 HMAC. Truncation is safe for an HMAC in a way it is not
# for a bare digest -- the preimage is protected by the key, not by length --
# and 32 characters keeps the value inside the OPAQUE_REF attribute shape.
_REFERENCE_LENGTH: Final[int] = 32
_TENANT_REFERENCE_LENGTH: Final[int] = 12

# A session id that never arrived is not a session whose id happens to be
# blank. Hashing "" would give every such event a real-looking reference that
# groups in ClickHouse as though they were one long session. All-zero is the
# same width and charset as a real reference, so it satisfies the OPAQUE_REF
# attribute shape, and no HMAC will collide with it.
MISSING_REFERENCE: Final[str] = "0" * _REFERENCE_LENGTH
MISSING_TENANT_REFERENCE: Final[str] = "0" * _TENANT_REFERENCE_LENGTH


def tenant_ref(tenant_id: Any) -> str:
    """Return the bounded deployment-wide tenant correlation reference.

    Tenant identifiers are not short public capabilities like session IDs, so
    the design intentionally uses a stable SHA-256 prefix for operations and
    lifecycle correlation without disclosing the configured identifier.
    """
    text = str(tenant_id or "").strip()
    if not text:
        return MISSING_TENANT_REFERENCE
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_TENANT_REFERENCE_LENGTH]

# A domain tag mixed into the HMAC input, so a session id and a feedback id
# that happened to be equal do not produce the same reference in both stores.
#
# The session domain is deliberately empty: prefixing it too would change every
# session_ref this deployment has already written, orphaning up to 30 days of
# silver rows from the sessions they belong to. Separating one of the two
# spaces is sufficient, and it is the one with no history.
_SESSION_DOMAIN: Final[str] = ""
_FEEDBACK_DOMAIN: Final[str] = "feedback"


class SessionPseudonymizer:
    """Maps a session id to a reference that cannot be mapped back."""

    __slots__ = ("_key",)

    def __init__(self, *, key: bytes) -> None:
        self._key = key

    @classmethod
    def from_environment(cls) -> "SessionPseudonymizer":
        """Read the deployment key, falling back to a per-process random one.

        There is deliberately no default key: a constant in this file would be
        published with the repository, which pseudonymises nothing. A random
        fallback keeps the guarantee and costs comparability instead -- rows
        from different gateway processes no longer group by session -- which is
        a reporting gap an operator can see and fix, rather than a silent loss
        of the property this module exists for.
        """
        configured = (os.environ.get(SESSION_KEY_ENV) or "").strip()
        if configured:
            return cls(key=configured.encode("utf-8"))

        logger.warning(
            "%s is not set; session references will be keyed per process, so "
            "telemetry rows from different gateway processes or restarts will "
            "not group by session.",
            SESSION_KEY_ENV,
        )
        return cls(key=secrets.token_bytes(32))

    def reference(self, session_id: Any) -> str:
        """Never raises: telemetry must not be able to fail a request."""
        return self._domain_reference(_SESSION_DOMAIN, session_id)

    def feedback_reference(self, feedback_id: Any) -> str:
        """The reference ClickHouse holds instead of a feedback record id.

        Same key, different domain. Sharing the key keeps deployment simple;
        separating the domain means an analyst holding one reference cannot
        test it against the other store, because the same input never maps to
        the same output in both spaces.
        """
        return self._domain_reference(_FEEDBACK_DOMAIN, feedback_id)

    def _domain_reference(self, domain: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return MISSING_REFERENCE
        message = (f"{domain}:{text}" if domain else text).encode("utf-8")
        digest = hmac.new(self._key, message, hashlib.sha256)
        return digest.hexdigest()[:_REFERENCE_LENGTH]


_process_pseudonymizer: SessionPseudonymizer | None = None


def session_ref(session_id: Any) -> str:
    """The process-wide reference for a session id.

    Built on first use rather than at import so a test, or a deployment that
    sets the key after the module is loaded, still sees the configured key.
    """
    global _process_pseudonymizer
    if _process_pseudonymizer is None:
        _process_pseudonymizer = SessionPseudonymizer.from_environment()
    return _process_pseudonymizer.reference(session_id)


def feedback_ref(feedback_id: Any) -> str:
    """The process-wide reference for a feedback record id."""
    global _process_pseudonymizer
    if _process_pseudonymizer is None:
        _process_pseudonymizer = SessionPseudonymizer.from_environment()
    return _process_pseudonymizer.feedback_reference(feedback_id)
