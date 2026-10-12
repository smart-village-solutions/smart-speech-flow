"""The capability that binds a session to the first guest who activated it."""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from typing import Optional


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def issue_guest_token() -> tuple[str, str]:
    """A new token for the guest, and the digest the session keeps instead of it."""
    token = secrets.token_urlsafe(32)
    return token, _digest(token)


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
