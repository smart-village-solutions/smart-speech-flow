"""Only the audio processing adapter imports `audioop`, which Python 3.13 removes (#228).

The import graph is followed from app.py, the module uvicorn loads, through
every gateway import it can reach, including imports inside functions, so a
module the lifespan imports late is covered too.
"""

from __future__ import annotations

import ast
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"
PACKAGE = "services.api_gateway"


def _module_file(module: str) -> Path | None:
    parts = module.split(".")[2:]
    if not parts:
        return GATEWAY / "__init__.py"
    relative = Path(*parts)
    for candidate in (GATEWAY / relative.with_suffix(".py"), GATEWAY / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _package_of(module: str, path: Path) -> str:
    return module if path.name == "__init__.py" else module.rsplit(".", 1)[0]


def _imports(module: str, path: Path) -> tuple[set[str], set[str]]:
    """Gateway modules and top-level external modules that `module` imports."""
    gateway: set[str] = set()
    external: set[str] = set()
    package = _package_of(module, path)
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                (gateway if alias.name.startswith(PACKAGE) else external).add(
                    alias.name if alias.name.startswith(PACKAGE) else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                target = f"{base}.{node.module}" if node.module else base
            elif node.module and node.module.startswith(PACKAGE):
                target = node.module
            else:
                external.add((node.module or "").split(".")[0])
                continue
            gateway.add(target)
            gateway.update(f"{target}.{alias.name}" for alias in node.names)
    return gateway, external


def _production_modules() -> dict[str, set[str]]:
    """Every gateway module reachable from app.py, with its external imports."""
    reached: dict[str, set[str]] = {}
    pending = [f"{PACKAGE}.app"]
    while pending:
        module = pending.pop()
        path = _module_file(module)
        if module in reached or path is None:
            continue
        gateway, external = _imports(module, path)
        reached[module] = external
        pending.extend(gateway)
    return reached


def test_only_the_audio_processing_adapter_imports_audioop() -> None:
    modules = _production_modules()

    importers = {module for module, external in modules.items() if "audioop" in external}

    assert f"{PACKAGE}.pipeline_logic" in modules, "the walk must reach the pipeline"
    assert importers == {f"{PACKAGE}.audio_processing"}
