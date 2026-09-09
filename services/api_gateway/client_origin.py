"""Exact additional browser origin for a standalone SSF frontend."""

import os
from urllib.parse import urlsplit


def configured_client_origin() -> str | None:
    """Accept an HTTPS CLIENT_BASE_URL without credentials, query or fragment."""
    value = os.environ.get("CLIENT_BASE_URL", "").strip()
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or any(char.isspace() for char in value)
            or "*" in value
        ):
            return None
        # Accessing port validates malformed and out-of-range values.
        port = url.port
    except ValueError:
        return None
    hostname = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    authority = f"{hostname}:{port}" if port not in (None, 443) else hostname
    return f"https://{authority}"
