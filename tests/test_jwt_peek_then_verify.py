"""An unverified JWT read must sit beside the verification that justifies it.

The gateway peeks at a token's issuer before verifying it, to find the tenant
and its signing keys. That is safe only because the same token is verified with
a key before any claim is trusted. Keeping both decodes in one function makes
that argument local to the reader, and it is exactly the "peek then verify"
shape SonarCloud's python:S5659 accepts; splitting them across helpers failed
the security gate on PR #408.
"""

import ast
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"


def _is_jwt_decode(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "decode"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "jwt"
    )


def _skips_signature(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "options" and isinstance(keyword.value, ast.Dict):
            for key, value in zip(keyword.value.keys, keyword.value.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "verify_signature"
                    and isinstance(value, ast.Constant)
                    and value.value is False
                ):
                    return True
    return False


def _token_name(call: ast.Call) -> str | None:
    first = call.args[0] if call.args else None
    return first.id if isinstance(first, ast.Name) else None


def _unpaired_peeks(source: str) -> list[int]:
    unpaired = []
    tree = ast.parse(source)
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decodes = [node for node in ast.walk(function) if _is_jwt_decode(node)]
        verified = {
            _token_name(call)
            for call in decodes
            if not _skips_signature(call) and len(call.args) >= 2
        }
        unpaired.extend(
            call.lineno
            for call in decodes
            if _skips_signature(call) and _token_name(call) not in verified
        )
    return unpaired


def test_every_unverified_decode_is_verified_in_the_same_function():
    offenders = {
        str(path.relative_to(GATEWAY)): lines
        for path in GATEWAY.rglob("*.py")
        if "tests" not in path.relative_to(GATEWAY).parts
        and (lines := _unpaired_peeks(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_the_guard_tells_paired_from_split_peeks():
    paired = (
        "def f(token, key):\n"
        "    jwt.decode(token, options={'verify_signature': False})\n"
        "    return jwt.decode(token, key, algorithms=['RS256'])\n"
    )
    split = (
        "def peek(token):\n"
        "    return jwt.decode(token, options={'verify_signature': False})\n"
        "def verify(token, key):\n"
        "    return jwt.decode(token, key, algorithms=['RS256'])\n"
    )
    assert _unpaired_peeks(paired) == []
    assert _unpaired_peeks(split) == [2]
