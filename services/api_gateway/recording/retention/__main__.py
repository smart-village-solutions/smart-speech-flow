"""The retention worker of one archive site (runbook recording-retention-deployment.md).

    python -m services.api_gateway.recording.retention run
    python -m services.api_gateway.recording.retention once
    python -m services.api_gateway.recording.retention acknowledge-restore --operator NAME
    python -m services.api_gateway.recording.retention erase --tenant T --conversation C \
        --reason R --operator NAME
    python -m services.api_gateway.recording.retention replay-erasures --operator NAME

`run` loops for good, `once` makes one pass and prints its report, and
`acknowledge-restore` accepts the database's current audit positions after a
restore, so destructive steps resume. `erase` crypto-shreds one conversation
early and appends it to the host's erasure log, outside the database, so
`replay-erasures` can repeat every logged erasure after a restore. Exit codes:
0 ok, 1 failed or refused, 2 usage, 3 erased but not logged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Final

from ...clock import utc_now
from ..repository import RecordingStorageUnavailable
from ..storage.archive import ArchiveError
from ..storage.s3 import S3ArchiveStore, S3Client
from ..storage.settings import ArchiveConfigError
from .decisions import RetentionRefusedError
from .restore_guard import AuditHighWater
from .settings import WorkerSettings
from .store import PostgresRetentionStore
from .worker import RetentionWorker

CONNECT_RETRY_SECONDS = 30.0
ERASURE_LOG: Final[str] = "erasures.log"
PRIMARY_ONLY: Final[str] = "retention: erase runs on the primary site only"
# Already done, or gone: nothing to repeat.
_SETTLED: Final[frozenset[str]] = frozenset({"no_conversation", "conversation_shredded"})


@asynccontextmanager
async def opened(settings: WorkerSettings) -> AsyncIterator[RetentionWorker]:
    """The worker with its database pool and its store client, closed on the way out."""
    client = S3Client(settings.endpoint)  # validates the endpoint; opens nothing yet
    store = await PostgresRetentionStore.connect(settings)
    try:
        archive = S3ArchiveStore(client, lambda _tenant: settings.credentials)
        yield RetentionWorker(settings, store, archive, AuditHighWater(settings.state_dir))
    finally:
        await client.close()
        await store.close()


async def _once(settings: WorkerSettings) -> int:
    async with opened(settings) as worker:
        report = await worker.run_once()
    print(json.dumps(report.as_dict()))
    return 0


async def _run(settings: WorkerSettings) -> int:
    while True:
        try:
            async with opened(settings) as worker:
                await worker.run_forever()
        except RecordingStorageUnavailable:
            sys.stderr.write("Retention database unreachable; retrying\n")
            await asyncio.sleep(CONNECT_RETRY_SECONDS)


async def _conflicts(store: PostgresRetentionStore, tenants: list[str]) -> list[str]:
    lines = []
    for tenant in tenants:
        for conversation_id, reason, locked_until in await store.restore_conflicts(tenant):
            line = f"{reason} {tenant} {conversation_id}"
            if reason == "locked_beyond_date" and locked_until is not None:
                line += f" until {locked_until.isoformat()}"
            lines.append(line)
    return lines


async def _acknowledge(settings: WorkerSettings, operator: str, accept_conflicts: bool) -> int:
    """Resume destructive steps once nothing a restore may have lost is left unexplained."""
    store = await PostgresRetentionStore.connect(settings)
    try:
        tenants = await store.tenants()
        with AuditHighWater(settings.state_dir).locked() as guard:
            if guard.recheck:
                print(
                    f"retention: {len(guard.recheck)} tenants not yet re-read from the store;"
                    " run again after the worker's next pass",
                    file=sys.stderr,
                )
                return 1
            conflicts = await _conflicts(store, tenants)
            if conflicts and not accept_conflicts:
                print("\n".join(conflicts), file=sys.stderr)
                print(
                    f"retention: {len(conflicts)} versions to resolve before acknowledging"
                    " (recording-retention-deployment.md, Step 11)",
                    file=sys.stderr,
                )
                return 1
            marks = {}
            for tenant in tenants:
                if (mark := await store.audit_mark(tenant)) is not None:
                    marks[tenant] = mark
            guard.acknowledge(marks)
    finally:
        await store.close()
    print(f"restore acknowledged by {operator}: {len(marks)} tenants, destructive steps resume")
    return 0


def _append_erasure(state_dir: Path, line: str) -> None:
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(state_dir / ERASURE_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a") as log:
        log.write(line + "\n")
        log.flush()
        os.fsync(log.fileno())


async def _erase(settings: WorkerSettings, args: argparse.Namespace) -> int:
    if settings.site != "primary":
        print(PRIMARY_ONLY, file=sys.stderr)
        return 2
    conversation_id = str(uuid.UUID(args.conversation))
    if not 1 <= len(args.reason) <= 500:
        raise ValueError("the reason is 1 to 500 characters")
    now = utc_now()
    store = await PostgresRetentionStore.connect(settings)
    try:
        decision_id = await store.erase(
            args.tenant, conversation_id, now, args.operator, args.reason
        )
    except RetentionRefusedError as refused:
        print(f"retention: erasure refused: {refused.code}", file=sys.stderr)
        return 1
    finally:
        await store.close()
    line = json.dumps(
        {
            "at": now.isoformat(),
            "tenant_id": args.tenant,
            "conversation_id": conversation_id,
            "operator": args.operator,
            "reason": args.reason,
            "decision_id": decision_id,
        }
    )
    try:
        _append_erasure(settings.state_dir, line)
    except OSError:
        # Committed and shredded; only the record for a later restore is missing.
        print(f"erasure committed but not logged: {line}", file=sys.stderr)
        return 3
    print(f"erased {conversation_id}: decision {decision_id}")
    return 0


def _logged_erasures(state_dir: Path) -> list[Any]:
    try:
        text = (state_dir / ERASURE_LOG).read_text()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def _replay(settings: WorkerSettings, operator: str) -> int:
    """Erase again every logged conversation a restore brought back."""
    if settings.site != "primary":
        print(PRIMARY_ONLY, file=sys.stderr)
        return 2
    logged = _logged_erasures(settings.state_dir)
    replayed = skipped = refused = 0
    store = await PostgresRetentionStore.connect(settings)
    try:
        for entry in logged:
            reason = f"replay: {entry['reason']}"[:500]
            try:
                await store.erase(
                    entry["tenant_id"], entry["conversation_id"], utc_now(), operator, reason
                )
                replayed += 1
            except RetentionRefusedError as error:
                if error.code in _SETTLED:
                    skipped += 1
                    continue
                refused += 1
                print(f"refused {entry['conversation_id']}: {error.code}", file=sys.stderr)
    finally:
        await store.close()
    print(f"replayed {replayed}, skipped {skipped}, refused {refused}")
    return 1 if refused else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retention")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("once")
    acknowledge = commands.add_parser("acknowledge-restore")
    acknowledge.add_argument("--operator", required=True)
    # Only for listed versions found to be explained, such as a raised tenant retention.
    acknowledge.add_argument("--accept-conflicts", action="store_true")
    erase = commands.add_parser("erase")
    for option in ("--tenant", "--conversation", "--reason", "--operator"):
        erase.add_argument(option, required=True)
    commands.add_parser("replay-erasures").add_argument("--operator", required=True)
    return parser


def _dispatch(settings: WorkerSettings, args: argparse.Namespace) -> int:
    if args.command == "once":
        return asyncio.run(_once(settings))
    if args.command == "acknowledge-restore":
        return asyncio.run(_acknowledge(settings, args.operator, args.accept_conflicts))
    if args.command == "erase":
        return asyncio.run(_erase(settings, args))
    if args.command == "replay-erasures":
        return asyncio.run(_replay(settings, args.operator))
    return asyncio.run(_run(settings))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _dispatch(WorkerSettings.from_environment(), args)
    except (ArchiveConfigError, ValueError, KeyError) as error:
        # Configuration and argument errors name a setting or a field, never a secret.
        print(f"retention: {type(error).__name__}: {error}", file=sys.stderr)
    except (RecordingStorageUnavailable, ArchiveError, OSError) as error:
        print(f"retention: {type(error).__name__}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
