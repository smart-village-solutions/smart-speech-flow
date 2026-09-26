"""Load repository scripts by path; their file names are not importable modules."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_script(relative_path: str, module_name: str) -> ModuleType:
    """Execute `relative_path` from the repository root as a fresh module."""
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules[cls.__module__].
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_contract() -> ModuleType:
    return load_script("scripts/lib/ssf_auth_contract.py", "ssf_auth_contract")
