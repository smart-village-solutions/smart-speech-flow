"""Connecting the feedback database at startup, and the loops that keep it connected and maintained."""

import asyncio
import os
import sys
from typing import Any

from ..dependencies import GatewayDependencies

FEEDBACK_RECONCILIATION_INTERVAL_SECONDS = 300
FEEDBACK_RETENTION_INTERVAL_SECONDS = 3600
FEEDBACK_CONNECT_RETRY_SECONDS = 5
FEEDBACK_CONNECT_RETRY_CEILING_SECONDS = 60


def _feedback_password(variable: str) -> str | None:
    """The password arrives beside the DSN, never inside it.

    A generated password is not URL-safe: see
    PostgresFeedbackRepository.create.
    """
    return os.environ.get(variable, "").strip() or None


async def _connect_feedback_request_path(state: Any, dsn: str, sessions: Any) -> bool:
    """Wire POST /api/feedback. Returns False only when retrying could help."""
    if state.feedback_service is not None:
        return True

    # Imported inside their own guard: crypto.py depends on `cryptography`,
    # which reaches the image only as PyJWT's `[crypto]` extra. An ImportError
    # escaping this function would propagate through the lifespan and stop the
    # gateway booting -- turning a missing feedback dependency into a total
    # outage, which is the opposite of what this whole path promises. It has
    # to be its own block, because the handler below names an exception this
    # import is what binds.
    try:
        from .crypto import FeedbackCipher, MissingEncryptionKey
        from .repository import PostgresFeedbackRepository
        from .service import FeedbackService
        from .tenant import ConfiguredTenantResolver, SessionTenantResolver
    except ImportError as error:
        sys.stderr.write(
            f"Feedback persistence disabled: {type(error).__name__}; "
            "POST /api/feedback will answer 503\n"
        )
        return True

    try:
        cipher = FeedbackCipher.from_environment()
    except MissingEncryptionKey:
        # Terminal, not transient: no key appears later, and encrypting under
        # a generated one would store rows nobody could ever read back.
        sys.stderr.write(
            "Feedback persistence disabled: SSF_FEEDBACK_ENCRYPTION_KEY is missing "
            "or malformed; POST /api/feedback will answer 503\n"
        )
        return True

    try:
        repository = await PostgresFeedbackRepository.create(
            dsn=dsn, password=_feedback_password("SSF_FEEDBACK_DATABASE_PASSWORD")
        )
    except Exception as error:
        # Type name only: a connection error can carry the DSN, and the DSN
        # carries the database password.
        sys.stderr.write(
            f"Feedback persistence unavailable ({type(error).__name__}); "
            "POST /api/feedback will answer 503 until it connects\n"
        )
        return False

    state.feedback_repository = repository
    state.feedback_service = FeedbackService(
        repository=repository,
        cipher=cipher,
        # The session's own tenant; the configured one only for a legacy
        # session or a submission that names no session.
        tenant_resolver=SessionTenantResolver(
            fallback=ConfiguredTenantResolver.from_environment(),
        ),
        session_manager=sessions,
        telemetry=state.quality_telemetry,
        pseudonymizer=state.pseudonymizer,
    )
    sys.stderr.write("Feedback persistence ready\n")
    return True


async def _connect_feedback_read_path(state: Any, dsn: str) -> bool:
    """Wire the authorised Studio read endpoints. Returns False to retry.

    A third role and a third pool, because the read path's privileges are
    deliberately not the union of the other two: it may SELECT and write an
    access audit row, and it may not write or delete feedback. See migration
    003, which explains why neither existing role can serve these reads.

    An unset DSN is a supported deployment, not a fault: a site that never
    granted Studio read access keeps collecting feedback, and the read
    endpoints answer 503.
    """
    if not dsn:
        sys.stderr.write(
            "Feedback reading disabled: SSF_FEEDBACK_READER_DATABASE_URL is not set; "
            "the Studio feedback endpoints will answer 503\n"
        )
        return True

    if getattr(state, "feedback_read_service", None) is not None:
        return True

    # Its own import guard, for the reason _connect_feedback_request_path
    # documents: crypto.py's dependency arrives as an extra, and an ImportError
    # escaping here would stop the gateway booting.
    try:
        from .crypto import FeedbackCipher, MissingEncryptionKey
        from .read import FeedbackReadService
        from .repository import PostgresFeedbackReadRepository
    except ImportError as error:
        sys.stderr.write(
            f"Feedback reading disabled: {type(error).__name__}; "
            "the Studio feedback endpoints will answer 503\n"
        )
        return True

    try:
        cipher = FeedbackCipher.from_environment()
    except MissingEncryptionKey:
        sys.stderr.write(
            "Feedback reading disabled: SSF_FEEDBACK_ENCRYPTION_KEY is missing or "
            "malformed; the Studio feedback endpoints will answer 503\n"
        )
        return True

    try:
        repository = await PostgresFeedbackReadRepository.create(
            dsn=dsn,
            password=_feedback_password("SSF_FEEDBACK_READER_DATABASE_PASSWORD"),
        )
    except Exception as error:
        # Type name only: a connection error can carry the DSN, and the DSN
        # carries the database password.
        sys.stderr.write(
            f"Feedback reading unavailable ({type(error).__name__}); the Studio "
            "feedback endpoints will answer 503 until it connects\n"
        )
        return False

    state.feedback_read_repository = repository
    state.feedback_read_service = FeedbackReadService(repository=repository, cipher=cipher)
    sys.stderr.write("Feedback reading ready\n")
    return True


async def _connect_feedback_maintenance(state: Any, dsn: str) -> bool:
    """Wire the recovery and retention passes, reporting on their own.

    Separate from the request path in both directions: collecting feedback
    matters more than reconciling it, and a maintenance pool that never opens
    must not be announced as an endpoint outage.
    """
    if state.feedback_maintenance is not None:
        return True
    if not dsn:
        sys.stderr.write(
            "Feedback maintenance disabled: SSF_FEEDBACK_MAINTENANCE_DATABASE_URL "
            "is not set; analytics recovery and retention will not run\n"
        )
        return True

    from .maintenance import FeedbackMaintenance, FeedbackMaintenanceMetrics
    from .repository import PostgresFeedbackRepository

    try:
        repository = await PostgresFeedbackRepository.create(
            dsn=dsn,
            password=_feedback_password("SSF_FEEDBACK_MAINTENANCE_DATABASE_PASSWORD"),
        )
    except Exception as error:
        sys.stderr.write(
            f"Feedback maintenance unavailable ({type(error).__name__}); "
            "analytics recovery and retention are not running. "
            "POST /api/feedback is unaffected\n"
        )
        return False

    state.feedback_maintenance_repository = repository
    state.feedback_maintenance = FeedbackMaintenance(
        repository=repository,
        telemetry=state.quality_telemetry,
        metrics=FeedbackMaintenanceMetrics(state.prometheus_registry),
        pseudonymizer=state.pseudonymizer,
    )
    sys.stderr.write("Feedback maintenance ready\n")
    return True


async def _wire_feedback(
    state: Any,
    request_dsn: str,
    maintenance_dsn: str,
    sessions: Any,
    read_dsn: str = "",
) -> bool:
    """Wire both halves. Returns False only when retrying could help.

    The two are reached independently on purpose. Unsetting
    SSF_FEEDBACK_DATABASE_URL is the documented way to stop accepting feedback
    while keeping the database, and the rows already stored still carry a
    twelve-month expiry that the submission notice promises in ten languages.
    Gating the passes on the submission path would stop enforcing it with no
    code path having decided to.
    """
    if not request_dsn:
        sys.stderr.write(
            "Feedback persistence disabled: SSF_FEEDBACK_DATABASE_URL is not set; "
            "POST /api/feedback will answer 503\n"
        )
        connected = True
    else:
        connected = await _connect_feedback_request_path(state, request_dsn, sessions)

    maintained = await _connect_feedback_maintenance(state, maintenance_dsn)
    readable = await _connect_feedback_read_path(state, read_dsn)
    sys.stderr.flush()
    return connected and maintained and readable


async def feedback_connect_task(
    state: Any,
    request_dsn: str,
    maintenance_dsn: str,
    sessions: Any,
    read_dsn: str = "",
) -> None:
    """Keep retrying whichever half did not connect at startup.

    The gateway deliberately does not wait for a healthy feedback database --
    a failed migration must not cost every customer their session -- so on a
    first deploy the database is usually still running its init scripts when
    this process starts. Nothing else retries, so without this that ordinary
    race leaves POST /api/feedback answering 503 until someone restarts the
    container.
    """
    if not request_dsn and not maintenance_dsn and not read_dsn:
        return

    delay = FEEDBACK_CONNECT_RETRY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            delay = min(delay * 2, FEEDBACK_CONNECT_RETRY_CEILING_SECONDS)

            if await _wire_feedback(state, request_dsn, maintenance_dsn, sessions, read_dsn):
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"\u26a0\ufe0f Feedback connection attempt failed: {type(error).__name__}")


async def feedback_maintenance_task(state: Any) -> None:
    """Drive analytics recovery and retention expiry (#305).

    One task for both passes on different periods: reconciliation is a cheap
    indexed read and wants to be prompt, while deletion is neither and only
    one replica performs it per pass anyway.

    Nothing here raises. FeedbackMaintenance already contains its own failures,
    and the loop is guarded besides: a task that dies takes every future pass
    with it, which is how retention silently stops being enforced.
    """
    elapsed = 0

    while True:
        try:
            await asyncio.sleep(FEEDBACK_RECONCILIATION_INTERVAL_SECONDS)
            elapsed += FEEDBACK_RECONCILIATION_INTERVAL_SECONDS

            maintenance = getattr(state, "feedback_maintenance", None)
            if maintenance is None:
                continue

            await maintenance.reconcile_once()

            if elapsed >= FEEDBACK_RETENTION_INTERVAL_SECONDS:
                elapsed = 0
                await maintenance.expire_once()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"\u26a0\ufe0f Feedback maintenance pass failed: {type(error).__name__}")


def _feedback_dsns() -> tuple[str, str, str]:
    """The submission, maintenance and Studio-read DSNs, in that order."""
    feedback_dsn = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "").strip()
    # Reconciliation and retention are deployment-wide, so they connect as a
    # role the tenant policy does not filter -- see deploy/postgres/migrations/
    # 002_feedback_roles.sql. Sharing the request pool would leave both passes
    # seeing no rows and reporting success.
    maintenance_dsn = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "").strip()
    # A third role again, for the opposite reason: the Studio read endpoints
    # must stay inside the tenant policy while gaining the audit privileges the
    # submit path deliberately lacks. See 003_feedback_reader.sql.
    read_dsn = os.environ.get("SSF_FEEDBACK_READER_DATABASE_URL", "").strip()
    return feedback_dsn, maintenance_dsn, read_dsn


async def _close_feedback(dependencies: GatewayDependencies) -> None:
    pools_at_exit = (
        dependencies.feedback_repository,
        dependencies.feedback_maintenance_repository,
        dependencies.feedback_read_repository,
    )
    dependencies.feedback_repository = None
    dependencies.feedback_maintenance_repository = None
    dependencies.feedback_read_repository = None
    dependencies.feedback_service = None
    dependencies.feedback_read_service = None
    dependencies.feedback_maintenance = None
    for pool_at_exit in pools_at_exit:
        if pool_at_exit is not None:
            await pool_at_exit.close()
