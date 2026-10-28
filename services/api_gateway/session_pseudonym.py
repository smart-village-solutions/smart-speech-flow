"""Keyed, one-way session references for telemetry.

The gateway's log lines reduce session ids to ``sha256(session_id)[:12]`` via
``log_safety.safe_session_ref``. That is adequate for a log line and inadequate
here: session ids are 32-bit, so an unkeyed digest of one can be reversed by
enumerating the input space, and telemetry rows live for 30 days in a store
built to be joined and grouped. An HMAC keyed by a deployment secret closes
that, because the id space cannot be enumerated without the key.

Scope is deliberately narrow: this is the telemetry pipeline's pseudonymiser,
not a replacement for the logging helper. Converging the two is a separate
change, since it alters what appears in existing operational logs.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from collections.abc import Callable
from typing import Any, Final

logger = logging.getLogger(__name__)

SESSION_KEY_ENV: Final[str] = "SSF_QUALITY_TELEMETRY_SESSION_KEY"
# How long a recorded session keeps its random reference after it ends: late
# messages and guest feedback (SSF_FEEDBACK_GRACE_MINUTES) arrive after the end.
RECORDED_MARK_SECONDS: Final[float] = 24 * 3600

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
_RECORDING_DOMAIN: Final[str] = "recording"


class SessionPseudonymizer:
    """Maps a session id to a reference that cannot be mapped back.

    A recorded session's telemetry must not be joinable to its archive, not
    even by whoever holds the key and can enumerate the 32-bit session ids
    (spec §5.5): from its first yes on, it gets a random reference instead,
    held only in this process until RECORDED_MARK_SECONDS after the session
    ends, and its events name no language.
    """

    __slots__ = ("_key", "_recorded", "_clock")

    def __init__(self, *, key: bytes, clock: Callable[[], float] = time.monotonic) -> None:
        self._key = key
        self._clock = clock
        # Session id -> (random reference, when the mark lapses; None while live).
        self._recorded: dict[str, tuple[str, float | None]] = {}

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
        recorded = self._recorded_reference(session_id)
        if recorded is not None:
            return recorded
        return self._domain_reference(_SESSION_DOMAIN, session_id)

    def mark_recorded(self, session_id: Any) -> None:
        """The session has had a recording window: its telemetry goes unlinkable."""
        self._drop_lapsed()
        text = str(session_id or "").strip()
        if not text:
            return
        held = self._recorded.get(text)
        reference = held[0] if held else secrets.token_hex(_REFERENCE_LENGTH // 2)
        self._recorded[text] = (reference, None)

    def is_recorded(self, session_id: Any) -> bool:
        return self._recorded_reference(session_id) is not None

    def ended(self, session_id: Any) -> None:
        """The session is over; its mark lapses RECORDED_MARK_SECONDS from now."""
        text = str(session_id or "").strip()
        held = self._recorded.get(text)
        if held is not None:
            self._recorded[text] = (held[0], self._clock() + RECORDED_MARK_SECONDS)
        self._drop_lapsed()

    def _recorded_reference(self, session_id: Any) -> str | None:
        held = self._recorded.get(str(session_id or "").strip())
        if held is None or (held[1] is not None and self._clock() >= held[1]):
            return None
        return held[0]

    def _drop_lapsed(self) -> None:
        now = self._clock()
        lapsed = [sid for sid, (_, until) in self._recorded.items() if until and now >= until]
        for session_id in lapsed:
            del self._recorded[session_id]

    def feedback_reference(self, feedback_id: Any) -> str:
        """The reference ClickHouse holds instead of a feedback record id.

        Same key, different domain. Sharing the key keeps deployment simple;
        separating the domain means an analyst holding one reference cannot
        test it against the other store, because the same input never maps to
        the same output in both spaces.
        """
        return self._domain_reference(_FEEDBACK_DOMAIN, feedback_id)

    def recording_reference(self, session_id: Any) -> str:
        """The session reference a recorded conversation keeps (spec §13).

        Its own domain, so an archive row and a telemetry row of the same
        session carry different references and cannot be joined (§5.5).
        """
        return self._domain_reference(_RECORDING_DOMAIN, session_id)

    def _domain_reference(self, domain: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return MISSING_REFERENCE
        message = (f"{domain}:{text}" if domain else text).encode("utf-8")
        digest = hmac.new(self._key, message, hashlib.sha256)
        return digest.hexdigest()[:_REFERENCE_LENGTH]
