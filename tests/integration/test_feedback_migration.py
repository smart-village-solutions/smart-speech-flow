"""Migration 004 against PostgreSQL: rows from before it are converted, not lost.

Runs 001 and 004 in a scratch schema as the owner, so the shared `feedback`
table is untouched and the conversion is exercised on a table holding old rows,
which a fresh volume never has.

    SSF_FEEDBACK_OWNER_DATABASE_URL=postgresql://... \
    pytest tests/integration/test_feedback_migration.py --run-integration
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from services.api_gateway.feedback.crypto import FeedbackCipher
from services.api_gateway.feedback.text_answers import open_text_answers

pytestmark = pytest.mark.integration

OWNER_DSN = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_URL", "")
OWNER_PASSWORD = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_PASSWORD") or None

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "deploy" / "postgres" / "migrations"
BUNDLED_SNAPSHOT = json.loads(
    (ROOT / "tests" / "fixtures" / "feedback" / "bundled_form.json").read_text(encoding="utf-8")
)
CIPHER = FeedbackCipher(key=b"7" * 32)
NEW_CHECKS = [
    "feedback_audience_check",
    "feedback_form_source_check",
    "feedback_revision_check",
    "feedback_numeric_answers_check",
    "feedback_form_snapshot_check",
    "feedback_text_legacy_check",
]

_OLD_ROW = """
INSERT INTO feedback (
    feedback_id, tenant_id, session_ref, translation_quality, performance,
    usability, net_promoter_score, improvements_ciphertext, form_version,
    retention_policy_version, consent_snapshot, analytics_event_id,
    analytics_state, created_at, expires_at
) VALUES ($1, 'tenant-a', $2, 4, 5, 3, 9, $3, 'v1', 'v1-12-months',
          '{}'::jsonb, $4, 'pending', $5, $6)
"""


def _sql(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


@pytest.fixture
async def scratch():
    connection = await asyncpg.connect(dsn=OWNER_DSN, password=OWNER_PASSWORD)
    schema = f"migration_probe_{uuid4().hex[:12]}"
    await connection.execute(f"CREATE SCHEMA {schema}")
    await connection.execute(f"SET search_path TO {schema}")
    try:
        await connection.execute(_sql("001_feedback.sql"))
        yield connection
    finally:
        await connection.execute(f"DROP SCHEMA {schema} CASCADE")
        await connection.close()


async def _old_row(connection: asyncpg.Connection, *, session_ref: str, text: str | None):
    feedback_id = uuid4()
    envelope = (
        None
        if text is None
        else CIPHER.encrypt(text, feedback_id=feedback_id, tenant_id="tenant-a")
    )
    now = datetime.now(timezone.utc)
    await connection.execute(
        _OLD_ROW, feedback_id, session_ref, envelope, uuid4(), now, now + timedelta(days=365)
    )
    return feedback_id


async def _columns(connection: asyncpg.Connection) -> set[str]:
    rows = await connection.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'feedback'"
    )
    return {row["column_name"] for row in rows}


async def test_an_old_row_is_converted_and_its_text_stays_readable(scratch) -> None:
    guest = await _old_row(scratch, session_ref="a" * 32, text="Old improvement text")
    installation = await _old_row(scratch, session_ref="0" * 32, text=None)

    await scratch.execute(_sql("004_feedback_dynamic.sql"))

    row = await scratch.fetchrow("SELECT * FROM feedback WHERE feedback_id = $1", guest)
    assert row["audience"] == "guest"
    assert row["form_source"] == "bundled"
    assert row["configuration_revision"] is None
    assert row["form_locale"] is None
    assert json.loads(row["form_snapshot"]) == BUNDLED_SNAPSHOT
    assert json.loads(row["numeric_answers"]) == {
        "translationQuality": 4,
        "performance": 5,
        "usability": 3,
        "recommendation": 9,
    }
    assert row["text_answers_legacy"] is True
    assert open_text_answers(
        CIPHER,
        row["text_answers_ciphertext"],
        legacy=row["text_answers_legacy"],
        feedback_id=guest,
        tenant_id="tenant-a",
    ) == {"improvementIdeas": "Old improvement text"}

    other = await scratch.fetchrow("SELECT * FROM feedback WHERE feedback_id = $1", installation)
    assert other["audience"] == "installation"
    assert other["text_answers_ciphertext"] is None
    assert other["text_answers_legacy"] is False


async def test_the_old_columns_are_gone(scratch) -> None:
    await scratch.execute(_sql("004_feedback_dynamic.sql"))

    columns = await _columns(scratch)
    assert not columns & {
        "translation_quality",
        "performance",
        "usability",
        "net_promoter_score",
        "improvements_ciphertext",
    }
    assert {"audience", "numeric_answers", "text_answers_ciphertext"} <= columns


async def test_re_running_every_migration_is_safe(scratch) -> None:
    feedback_id = await _old_row(scratch, session_ref="a" * 32, text="kept")
    await scratch.execute(_sql("004_feedback_dynamic.sql"))
    before = await scratch.fetchrow("SELECT * FROM feedback WHERE feedback_id = $1", feedback_id)

    await scratch.execute(_sql("001_feedback.sql"))
    await scratch.execute(_sql("004_feedback_dynamic.sql"))

    after = await scratch.fetchrow("SELECT * FROM feedback WHERE feedback_id = $1", feedback_id)
    assert dict(after) == dict(before)
    constraints = await scratch.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'feedback'::regclass "
        "AND conname = ANY($1::text[])",
        NEW_CHECKS,
    )
    assert sorted(row["conname"] for row in constraints) == sorted(NEW_CHECKS)


@pytest.mark.parametrize(
    "column, value",
    [
        ("audience", "'visitor'"),
        ("form_source", "'imported'"),
        ("configuration_revision", "'sha256:abc'"),
        ("numeric_answers", "'[1]'::jsonb"),
        ("form_snapshot", "'{}'::jsonb"),
        ("text_answers_legacy", "TRUE"),
    ],
)
async def test_the_new_columns_refuse_what_the_gateway_never_writes(
    scratch, column: str, value: str
) -> None:
    feedback_id = await _old_row(scratch, session_ref="0" * 32, text=None)
    await scratch.execute(_sql("004_feedback_dynamic.sql"))

    with pytest.raises(asyncpg.CheckViolationError):
        await scratch.execute(
            f"UPDATE feedback SET {column} = {value} WHERE feedback_id = $1", feedback_id
        )
