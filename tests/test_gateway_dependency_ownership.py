"""No new module-level collaborators in the gateway (#228).

A gateway collaborator is built by its app's lifespan and reached through a
provider in services/api_gateway/dependencies.py, so a test can replace it per
app. A module-level instance, or an lru_cache on a zero-argument function, is
a process-wide singleton no test can replace that way. The ones that remain
are listed below with the PR that removes them. The list only shrinks.

A call counts as a construction when its name is CapWords (a class), a
factory (build_, create_, make_, init_, initialize_, get_), or a `Class.from_*`
classmethod. Loggers, compiled regexes and frozensets are lowercase calls, so
they pass without an entry.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"

# Constructed values that are configuration or routing, not collaborators.
VALUE_TYPES = frozenset({"APIRouter", "Field", "Path", "TypeVar", "TypedDict"})

ALLOWLIST = {
    ("app.py", "app"): "permanent: the ASGI entry point uvicorn and the Dockerfile target",
    ("app.py", "registry"): "adapter until PR7",
    ("app.py", "requests_total"): "adapter until PR7",
    ("app.py", "pipeline_admission_metrics"): "adapter until PR7",
    ("app.py", "refinement_metrics"): "adapter until PR7",
    ("app.py", "websocket_metrics"): "adapter until PR7",
    ("audio_storage.py", "audio_storage_disk_usage_bytes"): "adapter until PR7",
    ("audio_storage.py", "audio_files_total"): "adapter until PR7",
    ("audio_storage.py", "audio_cleanup_deleted_files_total"): "adapter until PR7",
    ("auth.py", "_key_cache"): "adapter until PR7",
    # Unwired in PR 6b: nothing imports websocket_fallback.py; PR7 deletes the module.
    ("websocket_fallback.py", "fallback_manager"): "adapter until PR7",
}

# Module globals still rebound through a `global` statement. Only shrinks.
GLOBAL_REBINDING_ALLOWLIST = {
    ("rate_limiter.py", "LATEST_RATE_LIMIT_MIDDLEWARE"): "adapter until PR7",
}

# The str-keyed compatibility adapter, and the unregistered legacy route
# module that still needs it (#230). No other gateway module may import it.
LEGACY_SESSION_IMPORTERS = frozenset({"legacy_session_manager.py", "session.py"})

_FACTORY = re.compile(r"^(build|create|make|init|initialize|get)_")


def _module_statements(body: list[ast.stmt]):
    for statement in body:
        if isinstance(statement, (ast.If, ast.Try, ast.With)):
            for part in ("body", "orelse", "finalbody"):
                yield from _module_statements(getattr(statement, part, []))
            for handler in getattr(statement, "handlers", []):
                yield from _module_statements(handler.body)
        else:
            yield statement


def _constructed(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute):
        owner = function.value
        if (
            function.attr.startswith("from_")
            and isinstance(owner, ast.Name)
            and owner.id[:1].isupper()
        ):
            return owner.id
        name = function.attr
    elif isinstance(function, ast.Name):
        name = function.id
    else:
        return None
    if name in VALUE_TYPES:
        return None
    return name if name[:1].isupper() or _FACTORY.match(name) else None


def module_level_constructions(source: str) -> set[str]:
    names: set[str] = set()
    for statement in _module_statements(ast.parse(source).body):
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if isinstance(statement.value, ast.Call) and _constructed(statement.value):
            names.update(
                node.id
                for target in targets
                for node in ast.walk(target)
                if isinstance(node, ast.Name)
            )
    return names


def zero_argument_cached_factories(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = node.args
        if arguments.posonlyargs or arguments.args or arguments.kwonlyargs:
            continue
        if arguments.vararg or arguments.kwarg:
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if name in {"lru_cache", "cache"}:
                found.add(node.name)
    return found


def rebound_globals(source: str) -> set[str]:
    return {
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Global)
        for name in node.names
    }


def imports_legacy_session_manager(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").endswith("legacy_session_manager"):
                return True
            if any(
                alias.name in {"legacy_session_manager", "LegacySessionManager"}
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.endswith("legacy_session_manager") for alias in node.names):
                return True
    return False


def _gateway_sources() -> dict[str, str]:
    return {
        path.relative_to(GATEWAY).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(GATEWAY.rglob("*.py"))
        if "tests" not in path.relative_to(GATEWAY).parts
    }


def _gateway_constructions() -> set[tuple[str, str]]:
    return {
        (module, name)
        for module, source in _gateway_sources().items()
        for name in module_level_constructions(source)
    }


def test_no_new_module_level_collaborators() -> None:
    unexpected = sorted(_gateway_constructions() - ALLOWLIST.keys())
    assert not unexpected, (
        "Construct these in build_gateway_dependencies and reach them through a "
        f"provider instead of at import time: {unexpected}"
    )


def test_every_allowlisted_adapter_still_exists() -> None:
    stale = sorted(ALLOWLIST.keys() - _gateway_constructions())
    assert not stale, f"Delete the allowlist entries for removed adapters: {stale}"


def test_every_allowlist_entry_names_its_end() -> None:
    for entry, reason in {**ALLOWLIST, **GLOBAL_REBINDING_ALLOWLIST}.items():
        assert re.fullmatch(r"adapter until PR[4-7]|permanent: .+", reason), entry


def test_no_zero_argument_cached_factories() -> None:
    cached = {
        (module, name)
        for module, source in _gateway_sources().items()
        for name in zero_argument_cached_factories(source)
    }
    assert not cached, (
        "A cached zero-argument factory is a singleton no test can replace per app; "
        f"build the service in the container instead: {sorted(cached)}"
    )


def test_no_new_global_rebinding() -> None:
    rebound = {
        (module, name)
        for module, source in _gateway_sources().items()
        for name in rebound_globals(source)
    }
    assert rebound == GLOBAL_REBINDING_ALLOWLIST.keys(), (
        "Hold the collaborator in the container instead of rebinding a module global; "
        "delete the allowlist entry once its global is gone. "
        f"Unexpected: {sorted(rebound - GLOBAL_REBINDING_ALLOWLIST.keys())}, "
        f"stale: {sorted(GLOBAL_REBINDING_ALLOWLIST.keys() - rebound)}"
    )


def test_only_the_legacy_adapter_reaches_the_legacy_session_manager() -> None:
    importers = {
        module
        for module, source in _gateway_sources().items()
        if imports_legacy_session_manager(source)
    }
    assert importers <= LEGACY_SESSION_IMPORTERS, (
        "Production code depends on TenantSessionManager; LegacySessionManager is "
        f"the compatibility adapter only: {sorted(importers - LEGACY_SESSION_IMPORTERS)}"
    )


def test_the_detectors_recognise_what_they_forbid() -> None:
    source = """
import logging
import re
from functools import cache, lru_cache

logger = logging.getLogger(__name__)
PATTERN = re.compile("x")
router = APIRouter(prefix="/api")
if True:
    store = TicketStore(backend)
service: Service = build_service()
client = Client.from_environment()
left, right = Pair()

@lru_cache(maxsize=1)
def factory():
    return Service()

@cache
def keyed(tenant):
    return Service()
"""
    assert module_level_constructions(source) == {"store", "service", "client", "left", "right"}
    assert zero_argument_cached_factories(source) == {"factory"}
    assert rebound_globals("def bind(gate):\n    global _GATE\n    _GATE = gate\n") == {"_GATE"}
    for legacy_import in (
        "from .legacy_session_manager import LegacySessionManager",
        "from services.api_gateway.legacy_session_manager import LegacySessionManager",
        "from . import legacy_session_manager",
        "import services.api_gateway.legacy_session_manager",
        "if TYPE_CHECKING:\n    from .legacy_session_manager import LegacySessionManager",
    ):
        assert imports_legacy_session_manager(legacy_import), legacy_import
    assert not imports_legacy_session_manager("from .session_manager import TenantSessionManager")
