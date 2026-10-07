"""The Studio v2 responses captured from production on 2026-10-07."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "studio_v2"
KASSEL = "runtime-tenant-kassel.json"
LABOR = "runtime-smart-city-labor.json"
INSTALLATION = "installation.json"


def load_fixture(name: str) -> dict[str, Any]:
    """A fresh copy, so a test may mutate it."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
