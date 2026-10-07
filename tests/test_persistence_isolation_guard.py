"""No persistence-authorising code may read frozen session configuration.

Only a live Studio read authorises a write. A frozen snapshot is presentation
state and can be stale, so reaching for it here would reintroduce exactly the
failure #299 exists to prevent.
"""

import ast
from pathlib import Path

import pytest

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"

# The modules that decide whether content may be kept.
AUTHORISING_MODULES = (
    "runtime_policy.py",
    "persistence_authorization.py",
    "consent_resolution.py",
)

# The v1 snapshot key, by any name or attribute.
FORBIDDEN = {"runtime_configuration"}
# A session's revision records which configuration it started on. Like the v1
# snapshot it replaced, it must never authorise a write. The same attribute on a
# live read (`policy.configuration_revision`) is allowed.
FROZEN_REVISION = "configuration_revision"


def _owner_name(node: ast.AST) -> str:
    """The nearest identifier the attribute is read from: `session`, `get_session`, ..."""
    while True:
        if isinstance(node, ast.Await):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Name):
            return node.id
        else:
            return ""


def _frozen_reads(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN:
            found.add(node.id)
        elif isinstance(node, ast.Constant) and node.value in FORBIDDEN:
            found.add(node.value)
        elif isinstance(node, ast.alias):
            name = node.asname or node.name.rsplit(".", 1)[-1]
            if name in FORBIDDEN:
                found.add(name)
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN:
                found.add(node.attr)
            elif node.attr == FROZEN_REVISION and "session" in _owner_name(node.value).lower():
                found.add(f"session.{FROZEN_REVISION}")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "session.configuration_revision",
        "self._session.configuration_revision",
        "(await sessions.get_session(key)).configuration_revision",
        "data['runtime_configuration']",
        "session.runtime_configuration",
        "from x import runtime_configuration",
    ],
)
def test_the_guard_catches_a_frozen_read(source: str) -> None:
    assert _frozen_reads(source)


@pytest.mark.parametrize(
    "source",
    [
        "policy.configuration_revision",
        "read.policy.configuration_revision",
        "live_policy.configuration_revision",
    ],
)
def test_the_guard_allows_the_live_reads_revision(source: str) -> None:
    assert not _frozen_reads(source)


def test_authorising_modules_never_read_frozen_configuration():
    offenders = {}
    for name in AUTHORISING_MODULES:
        path = GATEWAY / name
        assert path.is_file(), f"{name} is missing; update this guard"
        hits = _frozen_reads(path.read_text(encoding="utf-8"))
        if hits:
            offenders[name] = sorted(hits)
    assert not offenders, (
        f"persistence authorisation read frozen configuration: {offenders}"
    )
