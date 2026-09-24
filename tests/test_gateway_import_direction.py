"""Routes depend on services, never the reverse (#228, #347 §2).

Every import statement counts, including one inside a function or under
TYPE_CHECKING: a function-level import is how the old cycle between
ConversationService and routes/session.py was hidden.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"
PACKAGE = "services.api_gateway"
ROUTES = f"{PACKAGE}.routes"
# The composition root registers the routers, so it alone may import them.
ROUTE_IMPORTERS = {GATEWAY / "app.py"}
PROCESSING = f"{PACKAGE}.message_processing"
PROCESSING_IMPORTERS = {GATEWAY / "conversation_service.py"}


def _module_name(path: Path) -> str:
    parts = path.relative_to(GATEWAY.parents[1]).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(source: str, module: str, *, is_package: bool = False) -> Iterator[str]:
    """Every module an import statement anywhere in `source` may bind."""
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            yield target
            # `from package import submodule` binds the submodule too.
            yield from (f"{target}.{alias.name}" for alias in node.names)


def _production_modules() -> Iterator[Path]:
    for path in sorted(GATEWAY.rglob("*.py")):
        if "tests" not in path.relative_to(GATEWAY).parts:
            yield path


def _importers_of(prefix: str, *, exclude: Path | None = None) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _production_modules():
        if exclude is not None and exclude in path.parents:
            continue
        hits = sorted(
            {
                target
                for target in imported_modules(
                    path.read_text(encoding="utf-8"),
                    _module_name(path),
                    is_package=path.name == "__init__.py",
                )
                if target == prefix or target.startswith(f"{prefix}.")
            }
        )
        if hits:
            found[str(path.relative_to(GATEWAY))] = hits
    return found


def test_no_gateway_module_outside_routes_imports_from_routes() -> None:
    importers = _importers_of(ROUTES, exclude=GATEWAY / "routes")
    allowed = {str(path.relative_to(GATEWAY)) for path in ROUTE_IMPORTERS}

    assert {name: hits for name, hits in importers.items() if name not in allowed} == {}


def test_only_the_conversation_service_reaches_message_processing() -> None:
    importers = _importers_of(PROCESSING)

    assert set(importers) == {str(path.relative_to(GATEWAY)) for path in PROCESSING_IMPORTERS}


def test_the_scan_sees_function_level_and_type_checking_imports() -> None:
    source = """
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .routes.session import MessageResponse

class Service:
    async def process(self):
        from .routes import session
        import services.api_gateway.routes.admin
"""
    found = set(imported_modules(source, f"{PACKAGE}.conversation_service"))

    assert {
        f"{ROUTES}.session",
        f"{ROUTES}.session.MessageResponse",
        f"{ROUTES}.admin",
    } <= found
