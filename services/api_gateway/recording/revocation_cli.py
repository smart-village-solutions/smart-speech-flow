"""Run the revocation check for one tenant now (docs/operations/runbooks/recording-revocation.md).

    python -m services.api_gateway.recording.revocation_cli --tenant <id> [--allow-mass]

It reads the same environment as the gateway. Exit 0 when the run revoked what
it found, 1 when a guard skipped it, 2 when recording or Studio is not set up.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from types import SimpleNamespace

from ..studio_runtime_token import token_provider_from_environment
from .repository import PostgresRecordingRepository
from .revocation import RevocationCheck, operator_run
from .revocation_repository import PostgresRevocations
from .wiring import RECORDING_PASSWORD_ENV, recording_directory, recording_dsn


async def main(argv: Sequence[str]) -> int:
    password = os.environ.get(RECORDING_PASSWORD_ENV, "").strip() or None
    provider = token_provider_from_environment()
    if not recording_dsn() or password is None or provider is None:
        sys.stderr.write("Recording or Studio is not configured here\n")
        return 2
    repository = await PostgresRecordingRepository.create(dsn=recording_dsn(), password=password)
    try:
        directory = recording_directory(SimpleNamespace(studio_token_provider=provider))
        check = RevocationCheck(PostgresRevocations(repository.pool), directory)
        outcome = await operator_run(argv, check)
    finally:
        await repository.close()
    print(outcome)
    return 0 if outcome == "done" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
