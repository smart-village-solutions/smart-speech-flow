"""Fetch the live frontend the way an iPad does (#620, spec §6)."""

import gzip
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ATTEMPTS = 3
PAUSE_SECONDS = 5
# Refused, reset or timed-out connections (all OSError, as are URLError and BadGzipFile),
# truncated bodies and corrupt compressed bodies.
NETWORK_ERRORS = (OSError, HTTPException, EOFError, zlib.error)
TABLET_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "de-DE,de;q=0.9",
}


class UnreachableError(Exception):
    """The site did not answer usably."""


@dataclass(frozen=True)
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes


Getter = Callable[[str], Reply]


def decode(encoding: str, body: bytes) -> bytes:
    """Undo gzip or deflate; anything else is kept as sent, so its hash cannot match."""
    name = encoding.strip().lower()
    if name == "gzip":
        return gzip.decompress(body)
    if name == "deflate":
        return zlib.decompress(body)
    return body


def _once(url: str, timeout: float) -> Reply:
    try:
        with urlopen(Request(url, headers=TABLET_HEADERS), timeout=timeout) as reply:
            status, raw, received = reply.status, reply.read(), reply.headers
    except HTTPError as error:
        status, raw, received = error.code, error.read(), error.headers
    headers = {name.lower(): ", ".join(received.get_all(name)) for name in {*received.keys()}}
    return Reply(status, headers, decode(headers.get("content-encoding", ""), raw))


def fetch(url: str, timeout: float = 20, wait: Callable[[float], None] = time.sleep) -> Reply:
    """GET without cookies; an HTTP error is a reply, three network failures are UnreachableError."""
    for _ in range(ATTEMPTS - 1):
        try:
            return _once(url, timeout)
        except NETWORK_ERRORS:
            wait(PAUSE_SECONDS)
    try:
        return _once(url, timeout)
    except NETWORK_ERRORS as error:
        raise UnreachableError(f"{url}: {error}") from error
