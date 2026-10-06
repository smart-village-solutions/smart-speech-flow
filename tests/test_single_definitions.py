"""Helpers #346 consolidated must keep exactly one definition."""

import re
from pathlib import Path

import pytest

GATEWAY = Path(__file__).parents[1] / "services" / "api_gateway"


@pytest.mark.parametrize(
    ("name", "home"),
    [
        ("utc_now", "clock.py"),
        ("safe_session_ref", "log_safety.py"),
        ("redacted_exception_info", "log_safety.py"),
        ("parse_origin", "origin.py"),
    ],
)
def test_helper_is_defined_once(name: str, home: str) -> None:
    pattern = re.compile(rf"^[ \t]*def _?{name}\(", re.MULTILINE)
    definitions = sorted(
        str(path.relative_to(GATEWAY))
        for path in GATEWAY.rglob("*.py")
        if "tests" not in path.parts and pattern.search(path.read_text(encoding="utf-8"))
    )
    assert definitions == [home]


def test_session_references_are_hashed_in_one_place() -> None:
    """Copies of `safe_session_ref` hid under other names (`_safe_identifier`, `safe_identifier`)."""
    hashing = sorted(
        str(path.relative_to(GATEWAY))
        for path in GATEWAY.rglob("*.py")
        if "tests" not in path.parts and ".hexdigest()[:12]" in path.read_text(encoding="utf-8")
    )
    assert hashing == ["log_safety.py"]
