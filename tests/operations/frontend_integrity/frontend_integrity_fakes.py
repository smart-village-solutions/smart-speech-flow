"""A local frontend server and fake issues for the monitor tests."""

import gzip
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.frontend_integrity.record import version

COMMIT = "0123456789abcdef0123456789abcdef01234567"
POLICY = "default-src 'none'"
POLICY_HEADER = "Content-Security-Policy"


def write_site(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html><head><script src="/theme-init.js"></script>'
        '<script type="module" src="/assets/index-a.js"></script></head><body></body></html>\n'
    )
    (root / "theme-init.js").write_text("(() => {})();\n")
    (root / "assets" / "index-a.js").write_text("console.log('entry');\n" * 100)
    (root / "assets" / "lazy-b.js").write_text("export const strength = 1;\n")
    return root


def fingerprint(root: Path, header: str = POLICY_HEADER, policy: str = POLICY) -> dict:
    include = f'add_header {header} "{policy}" always;\n'
    return version(root, include, "ssf-backend-frontend:test", COMMIT, "2026-11-05T10:00:00Z")


@dataclass
class SiteBehaviour:
    root: Path
    policy_headers: dict[str, str] = field(default_factory=lambda: {POLICY_HEADER: POLICY})
    deep_link_body: bytes | None = None
    deep_link_headers: dict[str, str] | None = None
    broken_gzip: bool = False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 - the name http.server dispatches to
        behaviour: SiteBehaviour = self.server.behaviour
        status, body, deep_link = self._body(behaviour)
        headers = behaviour.policy_headers
        if deep_link and behaviour.deep_link_headers is not None:
            headers = behaviour.deep_link_headers
        gzipped = "gzip" in self.headers.get("Accept-Encoding", "")
        if gzipped:
            body = b"not gzip" if behaviour.broken_gzip else gzip.compress(body)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, behaviour: SiteBehaviour) -> tuple[int, bytes, bool]:
        path = self.path.split("?", 1)[0]
        target = behaviour.root / ("index.html" if path == "/" else path.lstrip("/"))
        if target.is_file():
            return 200, target.read_bytes(), False
        if path.startswith("/assets/"):
            return 404, b"not found", False
        return 200, behaviour.deep_link_body or (behaviour.root / "index.html").read_bytes(), True


class FrontendServer:
    def __init__(self, behaviour: SiteBehaviour):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.behaviour = behaviour

    def __enter__(self) -> str:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"{'http'}://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"{'http'}://127.0.0.1:{port}"


@dataclass
class FakeIssues:
    issue: dict | None = None
    marker: str | None = None
    created: list[tuple[str, str, str, list[str]]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    def find_open(self, label: str) -> dict | None:
        return self.issue

    def last_marker(self, issue: dict) -> str | None:
        return self.marker

    def create(self, title: str, body: str, label: str, assignees: list[str]) -> None:
        self.created.append((title, body, label, assignees))

    def comment(self, issue: dict, body: str) -> None:
        self.comments.append(body)
