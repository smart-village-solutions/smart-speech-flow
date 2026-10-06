"""Exact additional browser origin for a standalone SSF frontend."""

import os

from .origin import parse_origin


def configured_client_origin() -> str | None:
    """Accept an HTTPS CLIENT_BASE_URL that is a bare origin."""
    return parse_origin(os.environ.get("CLIENT_BASE_URL", "").strip(), require_https=True)
