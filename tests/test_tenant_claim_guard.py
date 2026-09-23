"""No gateway code may read the tenant from token claims (#363).

The tenant is the directory entry whose realm issued the token. auth.py alone
may look at studio_tenant_id, and only to reject a token that disagrees.
tenant_context.py names it too, but only to reject request-side selectors.
"""

import re
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"
CLAIM_READ = re.compile(r"""(\.get\(\s*|\[\s*)["']studio_tenant_id["']""")


def _claim_readers() -> list[str]:
    return sorted(
        str(path.relative_to(GATEWAY))
        for path in GATEWAY.rglob("*.py")
        if "tests" not in path.relative_to(GATEWAY).parts
        and CLAIM_READ.search(path.read_text(encoding="utf-8"))
    )


def test_only_auth_reads_the_tenant_claim():
    assert _claim_readers() == ["auth.py"]


def test_the_guard_recognises_both_read_forms():
    assert CLAIM_READ.search('principal.get("studio_tenant_id")')
    assert CLAIM_READ.search("claims[ 'studio_tenant_id' ]")
    assert not CLAIM_READ.search('"studio_tenant_id",')
