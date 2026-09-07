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

# A session id that never arrived is not a session whose id happens to be
# blank. Hashing "" would give every such event a real-looking reference that
# groups in ClickHouse as though they were one long session. All-zero is the
# same width and charset as a real reference, so it satisfies the OPAQUE_REF
# attribute shape, and no HMAC will collide with it.
MISSING_REFERENCE: Final[str] = "0" * _REFERENCE_LENGTH


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
        text = str(session_id or "").strip()
        if not text:
            return MISSING_REFERENCE
        digest = hmac.new(self._key, text.encode("utf-8"), hashlib.sha256)
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
