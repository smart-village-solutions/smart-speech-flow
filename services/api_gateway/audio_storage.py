"""
Audio Storage Service for SSF Backend

Manages persistent storage of audio files with automatic cleanup.
- Files: <SSF_AUDIO_BASE_DIR>/v2/<tenant_ref>/<session_id>/<original|translated>/<message_id>.wav
- Retention: 24 hours
- Cleanup: Hourly background job
"""

import copy
import fnmatch
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

from prometheus_client import CollectorRegistry, Counter, Gauge

from .clock import utc_now
from .log_safety import sanitize_log_value
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
WAV_GLOB_PATTERN = "*.wav"


class AudioStorageMetrics:
    """The audio store's series, on the registry /metrics serves (#426).

    The ssf-audio-storage alerts read when a retention pass last completed and
    what it failed to delete, not how much it deleted: a quiet deployment, or
    one with SSF_CONTENT_RETENTION_HOURS=0, deletes nothing on every healthy pass.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self.disk_usage_bytes = Gauge(
            "audio_storage_disk_usage_bytes",
            "Total disk usage in bytes for audio storage",
            ["directory"],
            registry=registry,
        )
        self.files = Gauge(
            "audio_files_total", "Total number of audio files", ["directory"], registry=registry
        )
        self.cleanup_deleted_files = Counter(
            "audio_cleanup_deleted_files_total",
            "Total number of audio files deleted by cleanup job",
            ["directory"],
            registry=registry,
        )
        self.cleanup_errors = Counter(
            "audio_cleanup_errors_total",
            "Failed deletions of expired audio, and audio directories cleanup could not read",
            registry=registry,
        )
        self.cleanup_last_run = Gauge(
            "audio_cleanup_last_run_timestamp_seconds",
            "Unix time the retention pass last completed, or the gateway started if none has",
            registry=registry,
        )
        # From start, not 0: the alert then waits its full window for a first pass.
        self.cleanup_last_run.set_to_current_time()
        # Exposed from the first scrape, so increase() has a prior sample.
        for variant in AudioVariant:
            self.cleanup_deleted_files.labels(directory=variant.value).inc(0)

    def record_cleanup(self, stats: dict) -> None:
        for variant in AudioVariant:
            self.cleanup_deleted_files.labels(directory=variant.value).inc(
                stats[f"deleted_{variant.value}"]
            )
        self.cleanup_errors.inc(stats["errors"])

    def record_pass_completed(self) -> None:
        self.cleanup_last_run.set_to_current_time()

    def record_disk_usage(self, stats: dict) -> None:
        for variant in AudioVariant:
            self.disk_usage_bytes.labels(directory=variant.value).set(
                stats[f"{variant.value}_bytes"]
            )
            self.files.labels(directory=variant.value).set(stats[f"{variant.value}_files"])


def _configured_base_dir() -> Path:
    # Default remains /data/audio for local/Docker parity, but CI can override it.
    return Path(os.environ.get("SSF_AUDIO_BASE_DIR", "/data/audio"))


# Retention policy. Zero disables automatic deletion so an operator removes
# content by hand, which is what the tester environment asks for. It never
# applies to refused content.
_DEFAULT_RETENTION_HOURS = 24
# Kept for the suites that compute a file age from it.
RETENTION_HOURS = _DEFAULT_RETENTION_HOURS


def retention_hours() -> int:
    """Hours to keep authorised content. Zero disables automatic deletion.

    Returns:
        The configured retention, falling back to the default for any value
        that is absent, unparseable or negative.
    """
    raw = os.environ.get("SSF_CONTENT_RETENTION_HOURS", "").strip()
    if not raw:
        return _DEFAULT_RETENTION_HOURS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_RETENTION_HOURS
    return value if value >= 0 else _DEFAULT_RETENTION_HOURS


_STORAGE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TENANT_REF = re.compile(r"^[0-9a-f]{12}$")


class AudioVariant(str, Enum):
    ORIGINAL = "original"
    TRANSLATED = "translated"


def _storage_identifier(value: str) -> str:
    if not _STORAGE_IDENTIFIER.fullmatch(value):
        raise ValueError("invalid storage identifier")
    return value


def audio_path(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    *,
    base_dir: Path,
) -> Path:
    """Return a v2 path without exposing the raw tenant identifier."""
    safe_message_id = _storage_identifier(message_id)
    return (
        base_dir / "v2" / key.tenant_ref / key.session_id / variant.value / f"{safe_message_id}.wav"
    )


def delete_message_audio(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    *,
    base_dir: Path,
) -> bool:
    """Delete one message's audio file, reporting whether it existed.

    Args:
        key: The tenant-scoped session the message belongs to.
        message_id: The message whose artefact is being removed.
        variant: Which of the two artefacts to remove.
        base_dir: The storage root.

    Returns:
        True when a file was removed, False when there was nothing to remove
        or the removal failed.
    """
    path = audio_path(key, message_id, variant, base_dir=base_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("Failed to delete refused audio")
        return False
    return True


def save_audio(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    data: bytes,
    *,
    base_dir: Path,
) -> Path:
    """Persist one audio artifact below its tenant and session scope."""
    if not data:
        raise ValueError("audio data cannot be empty")
    path = audio_path(key, message_id, variant, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info(
        "tenant_audio_saved",
        extra={"tenant_ref": key.tenant_ref, "variant": variant.value},
    )
    return path


def scoped_audio_url(
    key: TenantSessionKey,
    role: str,
    message_id: str,
    variant: AudioVariant,
) -> str:
    """Build an audio URL for the role authorized at the response boundary."""
    if role not in {"admin", "customer"}:
        raise ValueError("invalid audio role")
    safe_message_id = _storage_identifier(message_id)
    return f"/api/{role}/session/{key.session_id}/audio/" f"{safe_message_id}/{variant.value}.wav"


def scope_pipeline_audio_urls(
    metadata: Optional[dict[str, Any]],
    key: TenantSessionKey,
    role: str,
    message_id: str,
) -> Optional[dict[str, Any]]:
    """Copy pipeline metadata and replace reusable paths with role-scoped URLs."""
    if metadata is None:
        return None
    scoped = copy.deepcopy(metadata)
    pipeline_input = scoped.get("input")
    if isinstance(pipeline_input, dict) and pipeline_input.get("type") == "audio":
        pipeline_input["audio_url"] = scoped_audio_url(key, role, message_id, AudioVariant.ORIGINAL)
    steps = scoped.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            output = step.get("output")
            if isinstance(output, dict) and (
                "audio_url" in output or output.get("audio_available") is True
            ):
                output["audio_url"] = scoped_audio_url(
                    key, role, message_id, AudioVariant.TRANSLATED
                )
    return scoped


def _managed_variant(v2_root: Path, resolved_root: Path, filepath: Path) -> AudioVariant | None:
    """The variant of a regular WAV file in the fixed v2 layout, or None for anything else."""
    relative = filepath.relative_to(v2_root)
    if len(relative.parts) != 4:
        return None
    _tenant_ref, session_id, variant_name, filename = relative.parts
    if (
        variant_name not in {variant.value for variant in AudioVariant}
        or not _TENANT_REF.fullmatch(_tenant_ref)
        or not _STORAGE_IDENTIFIER.fullmatch(session_id)
        or not _STORAGE_IDENTIFIER.fullmatch(filename.removesuffix(".wav"))
        or filepath.is_symlink()
        or not filepath.is_file()
        or not filepath.resolve().is_relative_to(resolved_root)
    ):
        return None
    return AudioVariant(variant_name)


def _managed_v2_audio_files(
    base_dir: Path, unreadable: list[OSError] | None = None
) -> Iterator[tuple[AudioVariant, Path]]:
    """Yield only regular WAV files in the fixed v2 tenant/session layout.

    A directory that cannot be listed is appended to `unreadable` rather than
    skipped in silence, as `Path.rglob` would: its files are neither deleted nor
    counted, and only the caller knows whether that is a failure.
    """
    v2_root = base_dir / "v2"
    if not v2_root.is_dir() or v2_root.is_symlink():
        return
    resolved_root = v2_root.resolve()

    def note(error: OSError) -> None:
        # A directory removed mid-walk is a session's files going, not a fault.
        if isinstance(error, FileNotFoundError):
            return
        logger.warning("Audio storage directory could not be read")
        if unreadable is not None:
            unreadable.append(error)

    for directory, _subdirectories, filenames in os.walk(v2_root, onerror=note):
        for filename in fnmatch.filter(filenames, WAV_GLOB_PATTERN):
            filepath = Path(directory) / filename
            try:
                variant = _managed_variant(v2_root, resolved_root, filepath)
            except (OSError, ValueError):
                logger.warning("Skipped unsafe audio storage entry")
                continue
            if variant is not None:
                yield variant, filepath


def cleanup_old_audio_files(*, base_dir: Path) -> dict:
    """
    Delete audio files older than the configured retention.

    Returns:
        Statistics about deleted files:
        {
            "deleted_original": int,
            "deleted_translated": int,
            "total_deleted": int,
            "errors": int
        }
    """
    stats = {
        "deleted_original": 0,
        "deleted_translated": 0,
        "total_deleted": 0,
        "errors": 0,
    }

    keep_for = retention_hours()
    if keep_for == 0:
        logger.info("Audio cleanup disabled (SSF_CONTENT_RETENTION_HOURS=0)")
        return stats

    cutoff_time = utc_now() - timedelta(hours=keep_for)
    logger.info(
        "Starting audio cleanup (retention: %sh, cutoff: %s)",
        keep_for,
        sanitize_log_value(cutoff_time.isoformat()),
    )

    unreadable: list[OSError] = []
    for variant, filepath in _managed_v2_audio_files(base_dir, unreadable):
        try:
            file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime, timezone.utc)
            if file_mtime < cutoff_time:
                filepath.unlink()
                stats[f"deleted_{variant.value}"] += 1
                logger.debug(
                    "Deleted expired v2 audio",
                    extra={"variant": variant.value},
                )
        except FileNotFoundError:
            # Deleted since the walk listed it, by termination or the sweep.
            continue
        except Exception:
            logger.exception("Failed to delete expired v2 audio")
            stats["errors"] += 1
    stats["errors"] += len(unreadable)

    stats["total_deleted"] = stats["deleted_original"] + stats["deleted_translated"]
    logger.info("Audio cleanup completed: %s", sanitize_log_value(stats))

    return stats


def get_disk_usage(*, base_dir: Path) -> dict:
    """
    Get disk usage statistics for audio storage.

    Returns:
        {
            "total_bytes": int,
            "original_bytes": int,
            "translated_bytes": int,
            "original_files": int,
            "translated_files": int,
            "total_files": int
        }
    """
    stats = {
        "original_bytes": 0,
        "translated_bytes": 0,
        "original_files": 0,
        "translated_files": 0,
    }

    for variant, filepath in _managed_v2_audio_files(base_dir):
        try:
            stats[f"{variant.value}_bytes"] += filepath.stat().st_size
            stats[f"{variant.value}_files"] += 1
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("Failed to stat v2 audio")

    stats["total_bytes"] = stats["original_bytes"] + stats["translated_bytes"]
    stats["total_files"] = stats["original_files"] + stats["translated_files"]

    return stats


class AudioStore:
    """One app's v2 audio files, below the directory it was built with.

    `build_gateway_dependencies` builds one per app and hands it to the
    conversation service, the session manager and the retention cleanup, so
    every write, read and deletion of that app uses the same directory.
    """

    def __init__(self, base_dir: Path, metrics: AudioStorageMetrics | None = None) -> None:
        self.base_dir = base_dir
        # Without its app's series, as when a test builds a store, it counts into its own.
        self.metrics = metrics if metrics is not None else AudioStorageMetrics(CollectorRegistry())

    @classmethod
    def from_environment(cls, metrics: AudioStorageMetrics | None = None) -> "AudioStore":
        """A store under SSF_AUDIO_BASE_DIR as it is set now, not at import."""
        return cls(_configured_base_dir(), metrics)

    def path(self, key: TenantSessionKey, message_id: str, variant: AudioVariant) -> Path:
        return audio_path(key, message_id, variant, base_dir=self.base_dir)

    def save(
        self, key: TenantSessionKey, message_id: str, variant: AudioVariant, data: bytes
    ) -> Path:
        return save_audio(key, message_id, variant, data, base_dir=self.base_dir)

    def delete(self, key: TenantSessionKey, message_id: str, variant: AudioVariant) -> bool:
        return delete_message_audio(key, message_id, variant, base_dir=self.base_dir)

    def cleanup_expired(self) -> dict:
        stats = cleanup_old_audio_files(base_dir=self.base_dir)
        self.metrics.record_cleanup(stats)
        return stats

    def disk_usage(self) -> dict:
        stats = get_disk_usage(base_dir=self.base_dir)
        self.metrics.record_disk_usage(stats)
        return stats
