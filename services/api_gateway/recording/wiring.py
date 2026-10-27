"""Connecting recording mode at startup, and the loop that keeps trying.

Recording is optional per deployment and never fatal: without its database
or its secrets, the gateway serves conversations as before and the recording
routes answer 503.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Final

from ..dependencies import GatewayDependencies
from ..realtime_protocol import ConnectionState, Frame
from ..session_models import ClientType
from ..studio_recording_directory_client import StudioRecordingDirectoryClient
from ..studio_settings import studio_base_url
from ..studio_v2 import RecordingPolicy, RuntimeRead
from .ceremony import CeremonyService
from .ceremony_repository import PostgresCeremonyRepository
from .directory import StudioCustodianDirectory
from .keys import KeyEnrolmentService
from .secrets import MissingRecordingSecrets, RecordingSecrets
from .session_service import TICK_SECONDS, RecordingSessions

RECORDING_DSN_ENV: Final[str] = "SSF_RECORDING_DATABASE_URL"
RECORDING_PASSWORD_ENV: Final[str] = "SSF_RECORDING_DATABASE_PASSWORD"
RECORDING_CONNECT_RETRY_SECONDS: Final[int] = 5
RECORDING_CONNECT_RETRY_CEILING_SECONDS: Final[int] = 60


def recording_dsn() -> str:
    return os.environ.get(RECORDING_DSN_ENV, "").strip()


def _password() -> str | None:
    return os.environ.get(RECORDING_PASSWORD_ENV, "").strip() or None


def _custodian_directory(state: Any) -> StudioCustodianDirectory:
    """Studio's recording directory through the app's one token provider, if Studio is set up."""
    token_provider = getattr(state, "studio_token_provider", None)
    base_url = studio_base_url()
    if token_provider is None or not base_url:
        return StudioCustodianDirectory(None)
    try:
        client = StudioRecordingDirectoryClient(base_url, token_provider.get_token)
    except ValueError:
        return StudioCustodianDirectory(None)
    return StudioCustodianDirectory(client)


class WebSocketAnnouncer:
    """Recording frames go to sockets only: a poller cannot answer a ping."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def broadcast(self, key: Any, frame: Frame, role: ClientType | None) -> None:
        await self._manager.broadcast_to_session(
            key, frame, target_client_type=role, include_polling=False
        )

    def connected(self, key: Any, role: ClientType) -> bool:
        connections = self._manager.registry.session(key) or {}
        return any(
            connection.client_type is role and connection.state is ConnectionState.CONNECTED
            for connection in connections.values()
        )


def _policy_reader(state: Any) -> Any:
    async def read(tenant_id: str) -> RecordingPolicy | None:
        flow = state.studio_runtime_flow
        if flow is None:
            raise RuntimeError("Studio is not configured")
        runtime: RuntimeRead = await flow.client.fetch(tenant_id, f"recording-{uuid.uuid4().hex}")
        return runtime.policy.recording

    return read


def _recording_sessions(state: Any, repository: PostgresCeremonyRepository) -> RecordingSessions:
    async def recovery_key_ready(tenant_id: str) -> bool:
        return await repository.active_recovery_key(tenant_id) is not None

    return RecordingSessions(
        store=state.recording_state_store,
        announcer=WebSocketAnnouncer(state.websocket_manager),
        policy=_policy_reader(state),
        recovery_key_ready=recovery_key_ready,
        audit=repository.record_audit,
    )


def _attach_sessions(state: Any, sessions: RecordingSessions | None) -> None:
    state.recording_sessions = sessions
    state.websocket_manager.recording = sessions
    state.session_manager.recording = sessions


async def recording_tick_task(state: Any) -> None:
    """Advance recording conversations and ping their screens, once recording is wired."""
    while True:
        await asyncio.sleep(TICK_SECONDS)
        sessions = state.recording_sessions
        if sessions is None:
            continue
        try:
            await sessions.tick()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            sys.stderr.write(f"Recording tick failed ({type(error).__name__})\n")


async def connect_recording(state: Any, dsn: str) -> bool:
    """Wire the recording services. Returns False only when retrying could help."""
    if state.recording_keys is not None:
        return True
    if not dsn or _password() is None:
        # Compose always sets the URL; the password is what a host opts in with.
        sys.stderr.write(f"Recording disabled: {RECORDING_PASSWORD_ENV} is unset\n")
        return True
    try:
        secrets = RecordingSecrets.from_environment()
    except MissingRecordingSecrets as error:
        # Terminal, not transient: no secret appears later in a running container.
        sys.stderr.write(f"Recording disabled: {error}\n")
        return True
    try:
        repository = await PostgresCeremonyRepository.create(dsn=dsn, password=_password())
    except Exception as error:
        sys.stderr.write(f"Recording storage unavailable ({type(error).__name__}); retrying\n")
        return False
    try:
        await repository.register_gateway_key(
            secrets.signing_key_id, secrets.signing_public_key, datetime.now(timezone.utc)
        )
    except Exception as error:
        await repository.close()
        sys.stderr.write(f"Recording key registration failed ({type(error).__name__})\n")
        return False
    state.recording_repository = repository
    state.recording_secrets = secrets
    state.recording_keys = KeyEnrolmentService(
        repository=repository, server_layer=secrets.server_layer
    )
    state.recording_ceremony = CeremonyService(
        repository=repository, directory=_custodian_directory(state), secrets=secrets
    )
    _attach_sessions(state, _recording_sessions(state, repository))
    sys.stderr.write("Recording keys ready\n")
    return True


async def recording_connect_task(state: Any, dsn: str) -> None:
    """Keep retrying while the database is still initialising on a first deploy."""
    if not dsn or _password() is None:
        return
    delay = RECORDING_CONNECT_RETRY_SECONDS
    while state.recording_keys is None:
        try:
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECORDING_CONNECT_RETRY_CEILING_SECONDS)
            if await connect_recording(state, dsn):
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"⚠️ Recording connection attempt failed: {type(error).__name__}")


async def close_recording(dependencies: GatewayDependencies) -> None:
    repository = dependencies.recording_repository
    dependencies.recording_repository = None
    dependencies.recording_keys = None
    dependencies.recording_ceremony = None
    dependencies.recording_secrets = None
    _attach_sessions(dependencies, None)
    if repository is not None:
        await repository.close()
