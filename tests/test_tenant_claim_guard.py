"""No gateway code may read the tenant from token claims (#363).

The tenant is the directory entry whose realm issued the token. auth.py alone
may look at studio_tenant_id, and only to reject a token that disagrees.
tenant_context.py names it too, but only in the set of rejected request-side
selectors, which is not a read of the claim.
"""

import ast
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"
CLAIM = "studio_tenant_id"


def _aliases(tree: ast.AST) -> set[str]:
    """Names bound to the claim's string, such as TENANT_CLAIM = "studio_tenant_id"."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_claim(node.value, set()):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _is_claim(node: ast.AST | None, aliases: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == CLAIM
    return isinstance(node, ast.Name) and node.id in aliases


def _reads(source: str) -> list[int]:
    """Line numbers of claims[CLAIM], x.get(CLAIM, ...) and CLAIM in/not in x."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_claim(node.slice, aliases):
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and _is_claim(node.args[0], aliases)
        ):
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.Compare)
            and _is_claim(node.left, aliases)
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
        ):
            lines.append(node.lineno)
    return sorted(set(lines))


def _claim_readers() -> dict[str, list[int]]:
    return {
        str(path.relative_to(GATEWAY)): lines
        for path in sorted(GATEWAY.rglob("*.py"))
        if "tests" not in path.relative_to(GATEWAY).parts
        and (lines := _reads(path.read_text(encoding="utf-8")))
    }


def test_only_auth_reads_the_tenant_claim():
    assert list(_claim_readers()) == ["auth.py"]


def test_the_guard_recognises_every_read_form():
    samples = [
        'principal.get("studio_tenant_id")',
        "claims[ 'studio_tenant_id' ]",
        '"studio_tenant_id" in claims',
        '"studio_tenant_id" not in claims',
        'KEY = "studio_tenant_id"\nclaims.get(KEY, None)',
        'KEY: str = "studio_tenant_id"\nvalue = claims[KEY]',
        'KEY = "studio_tenant_id"\nif KEY in claims: pass',
    ]
    for sample in samples:
        assert _reads(sample), sample


def test_the_guard_ignores_what_is_not_a_read():
    for sample in [
        'SELECTORS = frozenset({"studio_tenant_id", "tenant_id"})',
        "name.lower() in SELECTORS",
        'detail = "no studio_tenant_id here"',
        'claims.get("sub")',
    ]:
        assert _reads(sample) == [], sample
