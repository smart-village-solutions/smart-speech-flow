"""
Audio Storage Service for SSF Backend

Manages persistent storage of audio files with automatic cleanup.
- Original audio files: /data/audio/original/
- Translated audio files: /data/audio/translated/
- Retention: 24 hours
- Cleanup: Hourly background job
"""

import base64
import copy
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

from .log_safety import sanitize_log_value
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
WAV_GLOB_PATTERN = "*.wav"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge

    # Disk usage metrics
    audio_storage_disk_usage_bytes = Gauge(
        "audio_storage_disk_usage_bytes",
        "Total disk usage in bytes for audio storage",
        ["directory"],
    )

    audio_files_total = Gauge(
        "audio_files_total", "Total number of audio files", ["directory"]
    )

    audio_cleanup_deleted_files_total = Counter(
        "audio_cleanup_deleted_files_total",
        "Total number of audio files deleted by cleanup job",
        ["directory"],
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("Prometheus client not available - metrics disabled")

# Storage paths
# Default remains /data/audio for local/Docker parity, but CI can override it.
AUDIO_BASE_DIR = Path(os.environ.get("SSF_AUDIO_BASE_DIR", "/data/audio"))
ORIGINAL_AUDIO_DIR = AUDIO_BASE_DIR / "original"
TRANSLATED_AUDIO_DIR = AUDIO_BASE_DIR / "translated"

# Retention policy
RETENTION_HOURS = 24
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
    base_dir: Path = AUDIO_BASE_DIR,
) -> Path:
    """Return a v2 path without exposing the raw tenant identifier."""
    safe_message_id = _storage_identifier(message_id)
    return (
        base_dir
        / "v2"
        / key.tenant_ref
        / key.session_id
        / variant.value
        / f"{safe_message_id}.wav"
    )


def save_audio(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    data: bytes,
    *,
    base_dir: Path = AUDIO_BASE_DIR,
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
    return (
        f"/api/{role}/session/{key.session_id}/audio/"
        f"{safe_message_id}/{variant.value}.wav"
    )


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
        pipeline_input["audio_url"] = scoped_audio_url(
            key, role, message_id, AudioVariant.ORIGINAL
        )
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


def _managed_v2_audio_files(
    base_dir: Path,
) -> Iterator[tuple[AudioVariant, Path]]:
    """Yield only regular WAV files in the fixed v2 tenant/session layout."""
    v2_root = base_dir / "v2"
    if not v2_root.is_dir() or v2_root.is_symlink():
        return
    resolved_root = v2_root.resolve()
    for filepath in v2_root.rglob(WAV_GLOB_PATTERN):
        try:
            relative = filepath.relative_to(v2_root)
            if len(relative.parts) != 4:
                continue
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
                continue
            yield AudioVariant(variant_name), filepath
        except (OSError, ValueError):
            logger.warning("Skipped unsafe audio storage entry")


def ensure_directories():
    """Ensure audio storage directories exist."""
    ORIGINAL_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Audio storage directories initialized: %s",
        sanitize_log_value(AUDIO_BASE_DIR),
    )


def save_original_audio(message_id: str, audio_base64: str) -> str:
    """
    Save original audio file to persistent storage.

    Args:
        message_id: Unique message identifier
        audio_base64: Base64-encoded audio data

    Returns:
        URL path to the saved audio file

    Raises:
        ValueError: If audio_base64 is invalid
        IOError: If file cannot be written
    """
    if not audio_base64:
        raise ValueError("audio_base64 cannot be empty")

    ensure_directories()

    # Decode base64 audio
    try:
        audio_data = base64.b64decode(audio_base64)
    except Exception as e:
        logger.exception("Failed to decode base64 audio")
        raise ValueError(f"Invalid base64 audio data: {e}")

    # Save to disk
    filename = f"input_{message_id}.wav"
    filepath = ORIGINAL_AUDIO_DIR / filename

    try:
        filepath.write_bytes(audio_data)
        logger.info(
            "Saved original audio: %s (%s bytes)",
            sanitize_log_value(filepath),
            len(audio_data),
        )
    except Exception as e:
        logger.exception("Failed to save audio file")
        raise IOError(f"Failed to save audio file: {e}")

    # Return URL path
    return f"/api/audio/{filename}"


def save_translated_audio(message_id: str, audio_base64: str) -> str:
    """
    Save translated audio file to persistent storage.

    Args:
        message_id: Unique message identifier
        audio_base64: Base64-encoded audio data

    Returns:
        URL path to the saved audio file

    Raises:
        ValueError: If audio_base64 is invalid
        IOError: If file cannot be written
    """
    if not audio_base64:
        raise ValueError("audio_base64 cannot be empty")

    ensure_directories()

    # Decode base64 audio
    try:
        audio_data = base64.b64decode(audio_base64)
    except Exception as e:
        logger.exception("Failed to decode base64 audio")
        raise ValueError(f"Invalid base64 audio data: {e}")

    # Save to disk
    filename = f"{message_id}.wav"
    filepath = TRANSLATED_AUDIO_DIR / filename

    try:
        filepath.write_bytes(audio_data)
        logger.info(
            "Saved translated audio: %s (%s bytes)",
            sanitize_log_value(filepath),
            len(audio_data),
        )
    except Exception as e:
        logger.exception("Failed to save audio file")
        raise IOError(f"Failed to save audio file: {e}")

    # Return URL path
    return f"/api/audio/{filename}"


def get_audio_file_path(filename: str) -> Optional[Path]:
    """
    Get absolute path to an audio file.

    Args:
        filename: Audio filename (e.g., "input_uuid.wav" or "uuid.wav")

    Returns:
        Absolute Path to the file, or None if not found
    """
    ensure_directories()

    # Check original directory
    if filename.startswith("input_"):
        filepath = ORIGINAL_AUDIO_DIR / filename
        if filepath.exists():
            return filepath

    # Check translated directory
    filepath = TRANSLATED_AUDIO_DIR / filename
    if filepath.exists():
        return filepath

    logger.warning("Audio file not found in managed storage")
    return None


def cleanup_old_audio_files(*, base_dir: Path = AUDIO_BASE_DIR) -> dict:
    """
    Delete audio files older than RETENTION_HOURS.

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

    cutoff_time = utc_now() - timedelta(hours=RETENTION_HOURS)
    logger.info(
        "Starting audio cleanup (retention: %sh, cutoff: %s)",
        RETENTION_HOURS,
        sanitize_log_value(cutoff_time.isoformat()),
    )

    for variant, filepath in _managed_v2_audio_files(base_dir):
        try:
            file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime, timezone.utc)
            if file_mtime < cutoff_time:
                filepath.unlink()
                stats[f"deleted_{variant.value}"] += 1
                logger.debug(
                    "Deleted expired v2 audio",
                    extra={"variant": variant.value},
                )
        except Exception:
            logger.exception("Failed to delete expired v2 audio")
            stats["errors"] += 1

    stats["total_deleted"] = stats["deleted_original"] + stats["deleted_translated"]
    logger.info("Audio cleanup completed: %s", sanitize_log_value(stats))

    # Update Prometheus metrics
    if PROMETHEUS_AVAILABLE:
        audio_cleanup_deleted_files_total.labels(directory="original").inc(
            stats["deleted_original"]
        )
        audio_cleanup_deleted_files_total.labels(directory="translated").inc(
            stats["deleted_translated"]
        )

    return stats


def get_disk_usage(*, base_dir: Path = AUDIO_BASE_DIR) -> dict:
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
        except Exception:
            logger.exception("Failed to stat v2 audio")

    stats["total_bytes"] = stats["original_bytes"] + stats["translated_bytes"]
    stats["total_files"] = stats["original_files"] + stats["translated_files"]

    # Update Prometheus metrics
    if PROMETHEUS_AVAILABLE:
        audio_storage_disk_usage_bytes.labels(directory="original").set(
            stats["original_bytes"]
        )
        audio_storage_disk_usage_bytes.labels(directory="translated").set(
            stats["translated_bytes"]
        )
        audio_files_total.labels(directory="original").set(stats["original_files"])
        audio_files_total.labels(directory="translated").set(stats["translated_files"])

    return stats
