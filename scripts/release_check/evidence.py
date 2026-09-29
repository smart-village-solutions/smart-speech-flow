"""The release check's report. Every registered secret is redacted on output.

Redaction happens when the report is rendered, not when a check is recorded,
because a token becomes known only after the checks that could mention it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

REDACTED = "[redacted]"


def session_ref(session_id: str) -> str:
    """The short hash the gateway logs, so a report never carries the capability."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str
    duration_ms: int


class Evidence:
    def __init__(self) -> None:
        self._checks: list[Check] = []
        self._secrets: set[str] = set()

    def add_secret(self, value: str) -> None:
        if value:
            self._secrets.add(value)

    def record(self, name: str, passed: bool, detail: str = "", duration_ms: int = 0) -> None:
        self._checks.append(Check(name, passed, detail, duration_ms))

    @property
    def checks(self) -> tuple[Check, ...]:
        return tuple(
            replace(check, name=self._redact(check.name), detail=self._redact(check.detail))
            for check in self._checks
        )

    @property
    def passed(self) -> bool:
        return bool(self._checks) and all(check.passed for check in self._checks)

    def to_json(self) -> str:
        report = {"passed": self.passed, "checks": [asdict(check) for check in self.checks]}
        return json.dumps(report, indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        checks = self.checks
        passed = sum(check.passed for check in checks)
        lines = [
            f"**Result: {'PASS' if self.passed else 'FAIL'}** ({passed}/{len(checks)} checks)",
            "",
            "| Check | Result | Detail | ms |",
            "|---|---|---|---|",
        ]
        for check in checks:
            result = "pass" if check.passed else "FAIL"
            lines.append(
                f"| {_cell(check.name)} | {result} | {_cell(check.detail)} | {check.duration_ms} |"
            )
        return "\n".join(lines) + "\n"

    def _redact(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, REDACTED)
        return text


def _cell(text: str) -> str:
    return text.replace("|", "\\|")
