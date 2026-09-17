"""No persistence-authorising code may read frozen session configuration.

Only a live Studio read authorises a write. A frozen snapshot is presentation
state and can be stale, so reaching for it here would reintroduce exactly the
failure #299 exists to prevent.
"""

import ast
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"

# The modules that decide whether content may be kept.
AUTHORISING_MODULES = (
    "runtime_policy.py",
    "persistence_authorization.py",
    "consent_resolution.py",
)

FORBIDDEN = {
    "RuntimeConfigurationSnapshot",
    "PresentationConfiguration",
    "runtime_configuration",
}


def _names(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name.rsplit(".", 1)[-1])
    return found


def test_authorising_modules_never_read_frozen_configuration():
    offenders = {}
    for name in AUTHORISING_MODULES:
        path = GATEWAY / name
        assert path.is_file(), f"{name} is missing; update this guard"
        hits = _names(ast.parse(path.read_text(encoding="utf-8"))) & FORBIDDEN
        if hits:
            offenders[name] = sorted(hits)
    assert not offenders, (
        f"persistence authorisation read frozen configuration: {offenders}"
    )
