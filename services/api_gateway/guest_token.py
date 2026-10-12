"""The capability that binds a session to the first guest who activated it."""

from __future__ import annotations

import hmac
import re
import secrets
from hashlib import sha256
from typing import Optional

# What the frontend generates: 32 random bytes, base64url without padding (43
# characters). The upper bound only keeps an oversized header out.
_WELL_FORMED = re.compile(r"[A-Za-z0-9_-]{43,128}")


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def issue_guest_token() -> tuple[str, str]:
    """A new token for the guest, and the digest the session keeps instead of it."""
    token = secrets.token_urlsafe(32)
    return token, _digest(token)


def claim_guest_token(presented: Optional[str]) -> tuple[str, str]:
    """The token that claims a session, and its digest.

    The browser chooses it and keeps it before it asks, so a retry after a
    lost response carries the same token and is admitted. A request without a
    well-formed one -- an older bundle, a script -- gets one from the server.
    """
    if presented is not None and _WELL_FORMED.fullmatch(presented):
        return presented, _digest(presented)
    return issue_guest_token()


def guest_token_admits(stored_digest: Optional[str], presented: Optional[str]) -> bool:
    """Whether a request may act as the session's guest.

    A session no guest has claimed -- still pending, or activated before tokens
    existed -- admits anyone, as every session did before.
    """
    if stored_digest is None:
        return True
    if not presented:
        return False
    return hmac.compare_digest(_digest(presented), stored_digest)
