"""
Audio Storage Service for SSF Backend

Manages persistent storage of audio files with automatic cleanup.
- Files: <SSF_AUDIO_BASE_DIR>/v2/<tenant_ref>/<session_id>/<original|translated>/<message_id>.wav
- Retention: per session, from <session_id>/retention.json; the short
  SSF_TERMINAL_RECORD_HOURS when it is missing or invalid
- Cleanup: Hourly background job
"""

import copy
import fnmatch
import json
import logging
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

from prometheus_client import CollectorRegistry, Counter, Gauge

from .clock import utc_now
from .content_retention import terminal_record_hours, valid_retention_hours
from .log_safety import sanitize_log_value
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
WAV_GLOB_PATTERN = "*.wav"


class AudioStorageMetrics:
    """The audio store's series, on the registry /metrics serves (#426).

    The ssf-audio-storage alerts read when a retention pass last completed and
    what it failed to delete, not how much it deleted: a quiet deployment, or
    one whose sessions captured a retention of 0, deletes nothing on every
    healthy pass.
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


# Beside a session's audio: {"hours": N}, the retention captured with granted
# consent. It is not a WAV, so the walk never mistakes it for audio.
RETENTION_MARKER = "retention.json"
_MARKER_MAX_BYTES = 64
_MARKER_TEMP_PREFIX = ".retention-"
# A marker write takes milliseconds; a temp file this old was left by a process that died.
_STALE_MARKER_TEMP_SECONDS = 3600


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


def read_retention_marker(session_dir: Path) -> int | None:
    """The hours a session directory's marker carries, or None when it has no valid one.

    A symlink is never followed: it could borrow another directory's "keep".
    """
    marker = session_dir / RETENTION_MARKER
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        if marker.stat().st_size > _MARKER_MAX_BYTES:
            return None
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"hours"}:
        return None
    return valid_retention_hours(payload["hours"])


def _write_retention_marker(session_dir: Path, hours: int) -> None:
    """Write the marker atomically, unless it already says the same."""
    if read_retention_marker(session_dir) == hours:
        return
    descriptor, temporary = tempfile.mkstemp(dir=session_dir, prefix=_MARKER_TEMP_PREFIX)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"hours": hours}, handle)
        os.replace(temporary, session_dir / RETENTION_MARKER)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_audio(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    data: bytes,
    *,
    base_dir: Path,
    retention_hours: int | None = None,
) -> Path:
    """Persist one audio artifact below its tenant and session scope.

    With `retention_hours` (captured with granted consent) the session's
    marker is written first, and a failure to write it fails the save: the
    short default the cleanup would apply instead can outlive a shorter
    retention. Without it the cleanup applies the short default.
    """
    if not data:
        raise ValueError("audio data cannot be empty")
    path = audio_path(key, message_id, variant, base_dir=base_dir)
    # The cleanup may remove an emptied directory between these steps; one
    # retry recreates it.
    for attempt in range(2):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if retention_hours is not None:
                _write_retention_marker(path.parents[1], retention_hours)
            path.write_bytes(data)
            break
        except FileNotFoundError:
            if attempt:
                raise
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


def _managed_sessions(
    base_dir: Path, unreadable: list[OSError] | None = None
) -> Iterator[tuple[Path, list[tuple[AudioVariant, Path]]]]:
    """Yield each session directory of the fixed v2 layout with its regular WAV files.

    Walked bottom-up, so a directory's files are collected before it is
    yielded. A directory that cannot be listed is appended to `unreadable`
    rather than skipped in silence, as `Path.rglob` would: its files are
    neither deleted nor counted, and only the caller knows whether that is a
    failure.
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

    files: dict[Path, list[tuple[AudioVariant, Path]]] = defaultdict(list)
    for directory, _subdirectories, filenames in os.walk(v2_root, topdown=False, onerror=note):
        current = Path(directory)
        for filename in fnmatch.filter(filenames, WAV_GLOB_PATTERN):
            filepath = current / filename
            try:
                variant = _managed_variant(v2_root, resolved_root, filepath)
            except (OSError, ValueError):
                logger.warning("Skipped unsafe audio storage entry")
                continue
            if variant is not None:
                files[filepath.parents[1]].append((variant, filepath))
        if _is_session_directory(v2_root, current):
            yield current, files.pop(current, [])


def _is_session_directory(v2_root: Path, directory: Path) -> bool:
    parts = directory.relative_to(v2_root).parts
    return (
        len(parts) == 2
        and _TENANT_REF.fullmatch(parts[0]) is not None
        and _STORAGE_IDENTIFIER.fullmatch(parts[1]) is not None
        and not directory.is_symlink()
        and not directory.parent.is_symlink()
    )


def _managed_v2_audio_files(
    base_dir: Path, unreadable: list[OSError] | None = None
) -> Iterator[tuple[AudioVariant, Path]]:
    """Yield only regular WAV files in the fixed v2 tenant/session layout."""
    for _session_dir, files in _managed_sessions(base_dir, unreadable):
        yield from files


def _remove_session_directory(session_dir: Path, hours: int | None) -> None:
    """Remove an emptied session directory; stop at the first entry that is not ours.

    `rmdir` refuses a directory a concurrent save has just written into. Only
    a marker this pass read is unlinked, so it can be put back; one it could
    not read may be a save's fresh write, and stays.
    """
    try:
        _remove_stale_marker_temps(session_dir)
        for variant in AudioVariant:
            variant_dir = session_dir / variant.value
            if variant_dir.is_symlink():
                return
            try:
                variant_dir.rmdir()
            except FileNotFoundError:
                continue
        if hours is not None:
            (session_dir / RETENTION_MARKER).unlink(missing_ok=True)
        session_dir.rmdir()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning(
            "Audio session directory without audio could not be removed",
            extra={"tenant_ref": session_dir.parent.name},
        )
        if hours is not None:
            _restore_marker(session_dir, hours)


def _remove_stale_marker_temps(session_dir: Path) -> None:
    stale_before = utc_now().timestamp() - _STALE_MARKER_TEMP_SECONDS
    for temporary in session_dir.glob(f"{_MARKER_TEMP_PREFIX}*"):
        if not temporary.is_symlink() and temporary.lstat().st_mtime < stale_before:
            temporary.unlink(missing_ok=True)


def _restore_marker(session_dir: Path, hours: int) -> None:
    try:
        _write_retention_marker(session_dir, hours)
    except OSError:
        logger.warning("Failed to restore the audio retention marker")


def _delete_expired(
    files: list[tuple[AudioVariant, Path]], cutoff_time: datetime, stats: dict
) -> bool:
    """Delete the expired files; report whether none of the session's audio remains."""
    remaining = False
    for variant, filepath in files:
        try:
            file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime, timezone.utc)
            if file_mtime >= cutoff_time:
                remaining = True
                continue
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
            remaining = True
    return not remaining


def cleanup_old_audio_files(*, base_dir: Path) -> dict:
    """
    Delete audio files older than their session's retention.

    Each session directory's marker carries the retention captured with
    granted consent; `0` keeps that directory's audio. A missing or invalid
    marker falls back to the short SSF_TERMINAL_RECORD_HOURS. A session
    directory left without audio is removed; a save racing that removal finds
    `rmdir` refused or retries into a recreated directory.

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
    now = utc_now()
    short_default = terminal_record_hours()
    logger.info("Starting audio cleanup (default retention: %sh)", short_default)

    unreadable: list[OSError] = []
    for session_dir, files in _managed_sessions(base_dir, unreadable):
        marker_hours = read_retention_marker(session_dir)
        keep_for = short_default if marker_hours is None else marker_hours
        if keep_for:
            emptied = _delete_expired(files, now - timedelta(hours=keep_for), stats)
        else:
            emptied = not files
        if emptied:
            _remove_session_directory(session_dir, marker_hours)
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
        self,
        key: TenantSessionKey,
        message_id: str,
        variant: AudioVariant,
        data: bytes,
        *,
        retention_hours: int | None = None,
    ) -> Path:
        return save_audio(
            key, message_id, variant, data, base_dir=self.base_dir, retention_hours=retention_hours
        )

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
