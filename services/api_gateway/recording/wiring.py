"""Connecting recording mode at startup, and the loop that keeps trying.

Recording is optional per deployment and never fatal: without its database
or its secrets, the gateway serves conversations as before and the recording
routes answer 503.
"""

from __future__ import annotations

import asyncio
import functools
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Final

from ..dependencies import GatewayDependencies
from ..realtime_protocol import ConnectionState, Frame
from ..session_models import ClientType, SessionStatus
from ..studio_recording_directory_client import StudioRecordingDirectoryClient
from ..studio_settings import studio_base_url
from ..studio_v2 import RecordingPolicy, RuntimeRead
from .archive_access import ArchiveAccess
from .archive_access_repository import PostgresArchiveAccess
from .archive_repository import PostgresArchiveRepository
from .archive_service import ChainStamper, ConversationArchive, stored_recorder
from .ceremony import CeremonyService
from .ceremony_repository import PostgresCeremonyRepository
from .directory import StudioCustodianDirectory
from .keys import KeyEnrolmentService
from .recovery_requests import RecoveryRequests
from .recovery_requests_repository import PostgresRecoveryRequests
from .reenrolment import ImmediateConfirmation, KeyReenrolment
from .reenrolment_repository import PostgresKeyReenrolment
from .retention.decisions_repository import PostgresRetentionDecisions
from .retention.metrics import SITES as RETENTION_SITES
from .secrets import MissingRecordingSecrets, RecordingSecrets
from .session_service import TICK_SECONDS, RecordingSessions
from .storage.s3 import S3ArchiveStore, S3Client
from .storage.settings import ArchiveConfigError, ArchiveSettings
from .storage.tenant_spools import TenantSpools
from .timestamps import TimestampAuthority

RECORDING_DSN_ENV: Final[str] = "SSF_RECORDING_DATABASE_URL"
RECORDING_PASSWORD_ENV: Final[str] = "SSF_RECORDING_DATABASE_PASSWORD"
RECORDING_CONNECT_RETRY_SECONDS: Final[int] = 5
RECORDING_CONNECT_RETRY_CEILING_SECONDS: Final[int] = 60
STAMP_INTERVAL_SECONDS: Final[float] = 30.0
RETENTION_STATUS_INTERVAL_SECONDS: Final[float] = 60.0


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


def _connect_archive(
    state: Any, repository: PostgresCeremonyRepository, secrets: RecordingSecrets
) -> ConversationArchive | None:
    """The archive, its spools and its stamper; None while this host has no archive store."""
    try:
        settings = ArchiveSettings.from_environment()
        if settings is None:
            sys.stderr.write("Recording archive disabled: SSF_ARCHIVE_ENDPOINT is unset\n")
            return None
        client = S3Client(settings.endpoint)
        archive_repository = PostgresArchiveRepository(repository.pool)
        store = S3ArchiveStore(client, settings.credentials_for)
        spools = TenantSpools(settings.spool_directory, store, stored_recorder(archive_repository))
        spools.recover()
    except (ArchiveConfigError, ValueError, OSError) as error:
        # The type only: a configuration error may quote a path or an endpoint.
        sys.stderr.write(f"Recording archive disabled ({type(error).__name__})\n")
        return None
    spools.start()
    archive = ConversationArchive(
        repository=archive_repository,
        spools=spools,
        secrets=secrets,
        recovery_key=repository.active_recovery_key,
        user_key=repository.active_user_key,
        session_ref=state.session_manager.pseudonymizer.recording_reference,
        # A tenant without a writer credential would spool forever: it cannot record.
        tenant_ready=lambda tenant_id: tenant_id in settings.writers,
        live_sessions=functools.partial(_live_sessions, state),
    )
    state.recording_archive = archive
    state.recording_archive_access = ArchiveAccess(
        repository=PostgresArchiveAccess(repository.pool),
        reader=store,
        spools=spools,
        secrets=secrets,
        names=_custodian_directory(state),
    )
    state.recording_spools = spools
    state.recording_archive_client = client
    state.recording_stamper = ChainStamper(
        archive_repository, TimestampAuthority(), lambda: tuple(settings.writers)
    )
    return archive


async def _live_sessions(state: Any, tenant_id: str) -> list[str]:
    """The tenant's sessions that have not ended: a recorded conversation outlives none."""
    sessions = await state.session_manager.store.list_for_tenant(tenant_id)
    return [session.id for session in sessions if session.status is not SessionStatus.TERMINATED]


def _recording_sessions(
    state: Any, repository: PostgresCeremonyRepository, archive: ConversationArchive | None
) -> RecordingSessions:
    async def recovery_key_ready(tenant_id: str) -> bool:
        return await repository.active_recovery_key(tenant_id) is not None

    return RecordingSessions(
        store=state.recording_state_store,
        announcer=WebSocketAnnouncer(state.websocket_manager),
        policy=_policy_reader(state),
        recovery_key_ready=recovery_key_ready,
        audit=repository.record_audit,
        archive=archive,
        pseudonymizer=state.session_manager.pseudonymizer,
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


async def recording_stamp_task(state: Any) -> None:
    """Timestamp chain heads whose entries have all reached the archive store (§11.2)."""
    while True:
        await asyncio.sleep(STAMP_INTERVAL_SECONDS)
        if state.recording_stamper is None:
            continue
        try:
            await stamp_once(state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            sys.stderr.write(f"Recording stamping failed ({type(error).__name__})\n")


async def recording_retention_status_task(state: Any) -> None:
    """Export the archive sites' retention heartbeats; a failed read keeps the last values.

    With an archive, recording can store, so both sites' workers must run
    (recording-retention-deployment.md): a site without a heartbeat counts as silent.
    """
    while True:
        await asyncio.sleep(RETENTION_STATUS_INTERVAL_SECONDS)
        if state.recording_retention is None:
            continue
        expected = RETENTION_SITES if state.recording_archive is not None else ()
        try:
            statuses = await state.recording_retention.worker_statuses()
            state.retention_worker_metrics.update(statuses, expected)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state.retention_worker_metrics.expect(expected)
            sys.stderr.write(f"Retention status read failed ({type(error).__name__})\n")


async def stamp_once(state: Any) -> None:
    archive, stamper = state.recording_archive, state.recording_stamper
    await archive.retry_pending_ends()
    # Before stamping, so a conversation whose session is gone is stamped in this pass.
    await archive.end_orphaned(stamper.tenants())
    await stamper.run_once()


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
    state.recording_reenrolment = KeyReenrolment(
        store=PostgresKeyReenrolment(repository.pool),
        server_layer=secrets.server_layer,
        confirmation=ImmediateConfirmation(),
    )
    state.recording_ceremony = CeremonyService(
        repository=repository, directory=_custodian_directory(state), secrets=secrets
    )
    state.recording_retention = PostgresRetentionDecisions(repository.pool)
    state.recording_recovery_requests = RecoveryRequests(
        repository=PostgresRecoveryRequests(repository.pool),
        keys=repository,
        names=_custodian_directory(state),
    )
    archive = _connect_archive(state, repository, secrets)
    _attach_sessions(state, _recording_sessions(state, repository, archive))
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
    dependencies.recording_recovery_requests = None
    dependencies.recording_reenrolment = None
    dependencies.recording_retention = None
    dependencies.recording_secrets = None
    sessions = dependencies.recording_sessions
    _attach_sessions(dependencies, None)
    if sessions is not None:
        await sessions.close()
    spools, client = dependencies.recording_spools, dependencies.recording_archive_client
    dependencies.recording_archive = None
    dependencies.recording_archive_access = None
    dependencies.recording_spools = None
    dependencies.recording_archive_client = None
    dependencies.recording_stamper = None
    if spools is not None:
        await spools.stop()
    if client is not None:
        await client.close()
    if repository is not None:
        await repository.close()
