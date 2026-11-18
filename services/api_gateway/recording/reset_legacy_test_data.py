"""Operator-only, tenant-scoped legacy test reset; dry-run unless explicitly confirmed.

Archive deletion is deliberately external: an operator must export the inventory,
clear its exact storage/spool targets using existing retention procedures, stop
writers, and confirm the unchanged database inventory before applying this reset.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .audit import AuditEvent
from .repository import append_audit
from .storage.archive import bucket_for

TABLES = frozenset(
    {
        "user_keys",
        "user_key_reenrolments",
        "recovery_ceremonies",
        "ceremony_participants",
        "ceremony_dealings",
        "ceremony_confirmations",
        "ceremony_dealers",
        "recovery_keys",
        "recovery_shares",
        "recovery_requests",
        "recovery_request_keys",
        "recovery_decisions",
        "recovery_partials",
        "recovery_rejections",
        "recovery_unrecoverable_keys",
        "conversations",
        "recording_windows",
        "conversation_keys",
        "key_wraps",
        "chain_entries",
        "stored_objects",
        "chain_stamps",
        "retention_decisions",
        "version_locks",
        "site_clearances",
        "verifications",
        "verification_notes",
        "revocation_runs",
        "organisation_keys",
        "key_preparations",
        "key_grants",
    }
)


class ResetRefusedError(ValueError):
    """The explicit target, inventory or disposable-generation checks failed."""


def deletion_order(tables: set[str], edges: list[tuple[str, str]]) -> list[str]:
    if any(child not in tables and parent in tables for child, parent in edges):
        raise ResetRefusedError("An unrecognized table depends on reset data")
    remaining = set(tables)
    result: list[str] = []
    while remaining:
        leaves = sorted(
            table
            for table in remaining
            if not any(parent == table and child in remaining for child, parent in edges)
        )
        if not leaves:
            raise ResetRefusedError("Cyclic reset dependencies require an updated tool")
        result.extend(leaves)
        remaining.difference_update(leaves)
    return result


def confirm_plan(plan: dict[str, Any], confirmation: str | None, storage_cleared: bool) -> None:
    expected = f"{plan['database']}:{plan['tenant']}:{plan['digest']}"
    if plan["generation"] != 1 or confirmation != expected or not storage_cleared:
        raise ResetRefusedError(
            "Legacy test generation, exact inventory confirmation and cleared storage are required"
        )


async def inventory(
    connection: asyncpg.Connection, database: str, tenant: str, storage_target: str
) -> dict[str, Any]:
    if await connection.fetchval("SELECT current_database()") != database:
        raise ResetRefusedError("Database target does not match the connected database")
    if not await connection.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"):
        raise ResetRefusedError("This offline reset requires the database operator role")
    await connection.execute("SELECT set_config('ssf.tenant_id',$1,true)", tenant)
    present = {
        row["table_name"]
        for row in await connection.fetch(
            "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='tenant_id'"
        )
    }
    if present - TABLES - {"audit_events", "recording_protocol"}:
        raise ResetRefusedError("Unknown tenant tables require review before reset")
    counts: dict[str, Any] = {}
    for table in sorted(TABLES & present):
        # Table identifiers come exclusively from the fixed allowlist; tenant is bound.
        query = f"SELECT count(*) AS count, md5(COALESCE(string_agg(md5(row_to_json(t)::text),' ' ORDER BY md5(row_to_json(t)::text)),'')) AS fingerprint FROM \"{table}\" t WHERE tenant_id=$1"  # nosec B608
        row = await connection.fetchrow(query, tenant)
        counts[table] = dict(row)
    objects = [
        dict(row)
        for row in await connection.fetch(
            "SELECT e.conversation_id::text, s.entry_id::text,s.object_type,s.version_id"
            " FROM stored_objects s JOIN chain_entries e USING(tenant_id,entry_id)"
            " WHERE s.tenant_id=$1 ORDER BY s.entry_id,s.object_type",
            tenant,
        )
    ]
    plan = {
        "database": database,
        "tenant": tenant,
        "storageTarget": storage_target,
        "bucket": bucket_for(tenant),
        "tables": counts,
        "objects": objects,
        "generation": await connection.fetchval(
            "SELECT generation FROM recording_protocol WHERE tenant_id=$1", tenant
        ),
    }
    for item in objects:
        item["key"] = f"{item['conversation_id']}/{item['entry_id']}/{item['object_type']}"
    plan["digest"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


async def reset(
    connection: asyncpg.Connection,
    *,
    database: str,
    tenant: str,
    storage_target: str,
    confirmation: str | None = None,
    storage_cleared: bool = False,
    apply: bool = False,
    writers_stopped: bool = False,
) -> dict[str, Any]:
    async with connection.transaction(isolation="serializable", readonly=not apply):
        if apply:
            if not writers_stopped:
                raise ResetRefusedError(
                    "Stop recording writers, uploaders and retention workers first"
                )
            await connection.execute("SET LOCAL lock_timeout='5s'")
            # Fixed identifiers only. Locks serialize inventory validation with all writers.
            await connection.execute(
                "LOCK TABLE "
                + ",".join(sorted(TABLES | {"recording_protocol"}))
                + " IN ACCESS EXCLUSIVE MODE"
            )
        plan = await inventory(connection, database, tenant, storage_target)
        if not apply:
            return {**plan, "applied": False}
        confirm_plan(plan, confirmation, storage_cleared)
        edges = [
            (row["child"], row["parent"])
            for row in await connection.fetch(
                "SELECT conrelid::regclass::text AS child,confrelid::regclass::text AS parent"
                " FROM pg_constraint WHERE contype='f'"
            )
        ]
        # A legacy resharing points back to its recovery key, whose original
        # ceremony is also a parent. Clear only this tenant's soon-to-be-deleted
        # resharing references; every other FK remains enforced throughout.
        await connection.execute(
            "UPDATE recovery_ceremonies SET kind='generation',recovery_key_id=NULL,"
            " previous_transcript_hash=NULL WHERE tenant_id=$1",
            tenant,
        )
        edges = [
            (child, parent)
            for child, parent in edges
            if (child, parent) != ("recovery_ceremonies", "recovery_keys")
        ]
        order = deletion_order(set(TABLES), edges)
        # Decided notes normally cannot be deleted. Offline operator reset is the
        # one explicit exception; transaction rollback also restores trigger state.
        await connection.execute(
            "ALTER TABLE verification_notes DISABLE TRIGGER verification_notes_in_review"
        )
        for table in order:
            query = f'DELETE FROM "{table}" WHERE tenant_id=$1'  # nosec B608
            await connection.execute(query, tenant)
        await connection.execute(
            "ALTER TABLE verification_notes ENABLE TRIGGER verification_notes_in_review"
        )
        await connection.execute(
            "UPDATE recording_protocol SET generation=2 WHERE tenant_id=$1", tenant
        )
        actor = "operator:" + await connection.fetchval("SELECT current_user")
        await append_audit(
            connection,
            AuditEvent(
                tenant,
                actor,
                "recording.protocol.test_reset",
                plan["digest"],
                datetime.now(timezone.utc),
            ),
        )
        return {**plan, "applied": True}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    dsn = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL")
    if not dsn:
        raise ResetRefusedError("SSF_RECORDING_OWNER_DATABASE_URL is required")
    connection = await asyncpg.connect(
        dsn, password=os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD"), command_timeout=30
    )
    try:
        return await reset(
            connection,
            database=args.database,
            tenant=args.tenant,
            storage_target=args.storage_target,
            confirmation=args.confirm,
            storage_cleared=args.storage_cleared,
            apply=args.apply,
            writers_stopped=args.writers_stopped,
        )
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--storage-target",
        required=True,
        help="Explicit archive endpoint/bucket/spool inventory target; no credentials",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--storage-cleared", action="store_true")
    parser.add_argument("--confirm", help="Exact DATABASE:TENANT:DIGEST from the reviewed dry-run")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(_run(args)), sort_keys=True))
        return 0
    except (ValueError, asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
        parser.exit(
            2,
            "Reset refused; check targets, operator access, unchanged inventory and offline prerequisites.\n",
        )


if __name__ == "__main__":
    raise SystemExit(main())
