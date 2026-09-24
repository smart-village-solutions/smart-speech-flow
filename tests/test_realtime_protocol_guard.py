"""Every realtime frame is built in realtime_protocol.py (#228 task 3.1).

A frame written as a dict literal elsewhere can drift from the builders the
frame contract pins, so no other gateway module may write a dict whose "type"
is a MessageType: neither `MessageType.X`, `MessageType.X.value`, nor the
string that value spells.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from services.api_gateway.realtime_protocol import MessageType

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"
PROTOCOL = GATEWAY / "realtime_protocol.py"
FRAME_TYPES = frozenset(member.value for member in MessageType)
# Only shrinks.
ALLOWLIST = {
    "legacy_session_manager.py": "the str-keyed compatibility adapter no app builds; moved unchanged",
}


def _is_message_type(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in FRAME_TYPES
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id == "MessageType"


def _type_values(node: ast.AST) -> Iterator[ast.expr]:
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "type":
                yield value
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        yield from (keyword.value for keyword in node.keywords if keyword.arg == "type")


def inline_frames(source: str) -> list[int]:
    """The lines of `source` that write a frame as a dict."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        for value in _type_values(node)
        if _is_message_type(value)
    )


def _gateway_modules() -> Iterator[Path]:
    for path in sorted(GATEWAY.rglob("*.py")):
        if "tests" not in path.relative_to(GATEWAY).parts and path != PROTOCOL:
            yield path


def test_only_the_protocol_module_writes_realtime_frames() -> None:
    found = {
        str(path.relative_to(GATEWAY)): lines
        for path in _gateway_modules()
        if (lines := inline_frames(path.read_text(encoding="utf-8")))
    }

    assert {name: lines for name, lines in found.items() if name not in ALLOWLIST} == {}


def test_the_allowlist_names_only_modules_that_still_need_it() -> None:
    for name in ALLOWLIST:
        assert inline_frames((GATEWAY / name).read_text(encoding="utf-8")), name


def test_the_protocol_module_itself_builds_frames() -> None:
    assert inline_frames(PROTOCOL.read_text(encoding="utf-8"))


def test_every_spelling_of_an_inline_frame_is_found() -> None:
    source = "\n".join(
        [
            'a = {"type": MessageType.ERROR.value, "error": "x"}',
            'b = {"type": MessageType.ERROR}',
            'c = {"type": "session_terminated"}',
            'd = dict(type="client_left")',
            'e = {"type": "audio"}',
            'f = {"kind": MessageType.ERROR.value}',
            'g = {"type": message.type}',
        ]
    )

    assert inline_frames(source) == [1, 2, 3, 4]
