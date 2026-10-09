"""Migration 004, read as text: what can be checked without a database.

tests/integration/test_feedback_migration.py runs it against PostgreSQL.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "postgres" / "migrations" / "004_feedback_dynamic.sql"
FIXTURE = ROOT / "tests" / "fixtures" / "feedback" / "bundled_form.json"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_converted_rows_get_the_bundled_snapshot() -> None:
    match = re.search(
        r"-- bundled-form-snapshot:begin\n'(?P<json>[^']*)'\n-- bundled-form-snapshot:end", _sql()
    )

    assert match is not None
    assert json.loads(match.group("json")) == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_it_needs_no_psql_variables() -> None:
    """apply.sh passes only passwords and the database name; this file needs neither."""
    assert ":'" not in _sql()
    assert ':"' not in _sql()


def test_it_drops_columns_only_once_and_never_a_table() -> None:
    sql = _sql()

    assert "DROP TABLE" not in sql.upper()
    drops = re.findall(r"DROP COLUMN (?!IF EXISTS)", sql, flags=re.IGNORECASE)
    assert drops == []


def test_it_runs_after_the_reader_role() -> None:
    names = sorted(path.name for path in MIGRATION.parent.glob("*.sql"))

    assert names.index(MIGRATION.name) == names.index("003_feedback_reader.sql") + 1


def test_the_conversion_holds_the_table_until_the_old_columns_are_gone() -> None:
    """A row inserted between the UPDATE and the DROP would keep NULL answers and
    lose its ratings, and SET NOT NULL would then fail on every re-run."""
    sql = _sql()
    lock = sql.find("LOCK TABLE feedback IN ACCESS EXCLUSIVE MODE")
    update = sql.find("UPDATE feedback SET")
    drop = sql.find("DROP COLUMN IF EXISTS translation_quality")

    assert -1 < lock < update < drop
    # One DO block is one transaction, so the lock lasts until the drop.
    assert sql.rfind("$$", 0, lock) == sql.rfind("$$", 0, update) == sql.rfind("$$", 0, drop)
