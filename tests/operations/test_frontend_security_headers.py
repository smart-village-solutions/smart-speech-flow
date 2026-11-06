"""Every response of the built frontend image carries the security headers (#620, spec §4).

nginx drops server-level add_header in any location that has its own add_header:
that is how every HTML page on production lost X-Frame-Options and nosniff.
"""

import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ssf-frontend-security-headers-test"
BUILD_ARGS = {
    "VITE_API_BASE_URL": "https://api.dialog.kassel.de",
    "VITE_WS_BASE_URL": "wss://api.dialog.kassel.de",
    "VITE_KEYCLOAK_URL": "https://auth.dialog.kassel.de",
    "VITE_KEYCLOAK_CLIENT_ID": "ssf-frontend",
    "VITE_BRAND": "kassel",
    "SSF_CSP_MODE": "enforce",
}
POLICY = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; "
    "connect-src 'self' blob: https://api.dialog.kassel.de wss://api.dialog.kassel.de https://auth.dialog.kassel.de; "
    "media-src 'self' blob:; frame-src https://auth.dialog.kassel.de; worker-src 'none'; manifest-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)
EXPECTED = {
    "content-security-policy": POLICY,
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "x-xss-protection": "1; mode=block",
}

pytestmark = pytest.mark.integration


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as reply:
            status, headers, body = reply.status, reply.headers, reply.read()
    except urllib.error.HTTPError as error:
        status, headers, body = error.code, error.headers, error.read()
    return (
        status,
        {name.lower(): ", ".join(headers.get_all(name)) for name in set(headers.keys())},
        body,
    )


def _wait_for(url: str) -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            if _get(url)[0] == 200:
                return
        except (urllib.error.URLError, ConnectionError):
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(url)
        time.sleep(0.5)


@pytest.fixture(scope="module")
def frontend():
    args = [part for key, value in BUILD_ARGS.items() for part in ("--build-arg", f"{key}={value}")]
    subprocess.run(
        ["docker", "build", *args, "--tag", IMAGE, "services/frontend"], check=True, cwd=ROOT
    )
    container = subprocess.check_output(
        ["docker", "run", "--detach", "--publish", "127.0.0.1::8080", IMAGE], text=True
    ).strip()
    try:
        address = subprocess.check_output(
            ["docker", "port", container, "8080/tcp"], text=True
        ).splitlines()[0]
        base = f"{'http'}://127.0.0.1:{address.rsplit(':', 1)[1]}"
        _wait_for(base + "/health")
        yield base
    finally:
        subprocess.run(["docker", "rm", "--force", container], check=True, capture_output=True)


def _assert_security_headers(headers: dict[str, str]) -> None:
    assert {name: headers.get(name) for name in EXPECTED} == EXPECTED
    assert "content-security-policy-report-only" not in headers


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/", 200),
        ("/join/header-probe", 200),
        ("/index.html", 200),
        ("/theme-init.js", 200),
        ("/health", 200),
        ("/assets/does-not-exist.js", 404),
    ],
)
def test_every_fixed_path_carries_the_security_headers(frontend, path, status):
    received, headers, _ = _get(frontend + path)

    assert received == status
    _assert_security_headers(headers)


def test_cache_rules_survive_the_includes(frontend):
    _, index_headers, index = _get(frontend + "/")
    entry = re.search(rb'src="(/assets/index-[\w-]+\.js)"', index).group(1).decode()
    _, entry_headers, _ = _get(frontend + entry)
    _, theme_headers, _ = _get(frontend + "/theme-init.js")

    _assert_security_headers(entry_headers)
    assert "no-store" in index_headers["cache-control"]
    assert entry_headers["cache-control"].endswith("public, immutable")
    assert theme_headers["cache-control"] == "no-cache"


def test_index_html_has_no_inline_script(frontend):
    _, _, index = _get(frontend + "/")

    assert re.findall(rb"<script(?![^>]*\bsrc=)[^>]*>", index) == []
