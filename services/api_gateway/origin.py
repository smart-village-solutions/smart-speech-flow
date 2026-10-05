"""The single definition of "a bare HTTP origin" for configured service URLs.

Four call sites used to spell this out longhand and had drifted apart (#346).
Two per-caller differences are intentional. `require_https`: the public
frontend origin feeds CORS and WebSocket checks, while Keycloak and Studio are
also reached over plain HTTP inside the local stack. `keep_default_port`: the
Keycloak origin becomes the token issuer, which is compared verbatim, so an
explicit `:443` must survive.
"""

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def parse_origin(
    value: str, *, require_https: bool = False, keep_default_port: bool = False
) -> str | None:
    """Return `scheme://host[:port]` for a bare origin, or None for anything else."""
    if any(character.isspace() for character in value) or "*" in value:
        return None
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        return None
    allowed = {"https"} if require_https else {"http", "https"}
    if (
        url.scheme not in allowed
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        return None
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    if port is None or (port == _DEFAULT_PORTS[url.scheme] and not keep_default_port):
        return f"{url.scheme}://{host}"
    return f"{url.scheme}://{host}:{port}"
