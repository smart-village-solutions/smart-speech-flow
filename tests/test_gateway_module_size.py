"""No gateway production module grows past 800 lines (#230).

The five that had, split along their responsibilities in #230's last PR. A module
that reaches the budget is the signal to split it, not to raise the budget.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "services" / "api_gateway"
BUDGET = 800
SKIPPED_DIRECTORIES = {"tests", "__pycache__"}


def _production_modules() -> list[Path]:
    modules = []
    for directory, subdirectories, files in os.walk(GATEWAY):
        subdirectories[:] = sorted(d for d in subdirectories if d not in SKIPPED_DIRECTORIES)
        modules.extend(Path(directory, name) for name in sorted(files) if name.endswith(".py"))
    return modules


def test_no_gateway_module_is_over_the_line_budget():
    oversized = sorted(
        (path.relative_to(ROOT).as_posix(), length)
        for path in _production_modules()
        if (length := len(path.read_text(encoding="utf-8").splitlines())) > BUDGET
    )

    assert oversized == [], f"over {BUDGET} lines: {oversized}"
