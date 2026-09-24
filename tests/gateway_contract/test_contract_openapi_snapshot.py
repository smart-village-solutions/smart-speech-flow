"""The gateway's OpenAPI document must not drift during the #228 refactor.

A deliberate API change regenerates the snapshot:

    SSF_UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/gateway_contract/test_contract_openapi_snapshot.py

and the regenerated file is reviewed as part of that change.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"
UPDATE_VARIABLE = "SSF_UPDATE_OPENAPI_SNAPSHOT"
MAX_DIFF_LINES = 200


def _render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_openapi_document_matches_committed_snapshot(openapi_document):
    current = _render(openapi_document)

    if os.environ.get(UPDATE_VARIABLE) == "1":
        SNAPSHOT.write_text(current, encoding="utf-8")

    committed = SNAPSHOT.read_text(encoding="utf-8")
    if current == committed:
        return

    diff = list(
        difflib.unified_diff(
            committed.splitlines(),
            current.splitlines(),
            fromfile="snapshots/openapi.json (committed)",
            tofile="app.openapi() (current)",
            lineterm="",
        )
    )
    shown = "\n".join(diff[:MAX_DIFF_LINES])
    if len(diff) > MAX_DIFF_LINES:
        shown += f"\n... {len(diff) - MAX_DIFF_LINES} more diff lines"
    raise AssertionError(
        "The gateway OpenAPI document drifted from the committed snapshot. "
        f"If the change is intended, rerun with {UPDATE_VARIABLE}=1 and review "
        f"the snapshot diff.\n{shown}"
    )
