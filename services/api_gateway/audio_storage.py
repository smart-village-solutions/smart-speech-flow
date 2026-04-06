"""
Audio Storage Service for SSF Backend

Manages persistent storage of audio files with automatic cleanup.
- Original audio files: /data/audio/original/
- Translated audio files: /data/audio/translated/
- Retention: 24 hours
- Cleanup: Hourly background job
"""

import base64
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


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


def ensure_directories():
    """Ensure audio storage directories exist."""
    ORIGINAL_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Audio storage directories initialized: {AUDIO_BASE_DIR}")


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
        logger.error(f"Failed to decode base64 audio: {e}")
        raise ValueError(f"Invalid base64 audio data: {e}")

    # Save to disk
    filename = f"input_{message_id}.wav"
    filepath = ORIGINAL_AUDIO_DIR / filename

    try:
        filepath.write_bytes(audio_data)
        logger.info(f"Saved original audio: {filepath} ({len(audio_data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to save audio file {filepath}: {e}")
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
        logger.error(f"Failed to decode base64 audio: {e}")
        raise ValueError(f"Invalid base64 audio data: {e}")

    # Save to disk
    filename = f"{message_id}.wav"
    filepath = TRANSLATED_AUDIO_DIR / filename

    try:
        filepath.write_bytes(audio_data)
        logger.info(f"Saved translated audio: {filepath} ({len(audio_data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to save audio file {filepath}: {e}")
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


def cleanup_old_audio_files() -> dict:
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
    ensure_directories()

    stats = {
        "deleted_original": 0,
        "deleted_translated": 0,
        "total_deleted": 0,
        "errors": 0,
    }

    cutoff_time = utc_now() - timedelta(hours=RETENTION_HOURS)
    logger.info(
        f"Starting audio cleanup (retention: {RETENTION_HOURS}h, cutoff: {cutoff_time})"
    )

    # Cleanup original audio
    for filepath in ORIGINAL_AUDIO_DIR.glob("*.wav"):
        try:
            file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime, UTC)
            if file_mtime < cutoff_time:
                filepath.unlink()
                stats["deleted_original"] += 1
                logger.debug(f"Deleted old original audio: {filepath}")
        except Exception as e:
            logger.error(f"Failed to delete {filepath}: {e}")
            stats["errors"] += 1

    # Cleanup translated audio
    for filepath in TRANSLATED_AUDIO_DIR.glob("*.wav"):
        try:
            file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime, UTC)
            if file_mtime < cutoff_time:
                filepath.unlink()
                stats["deleted_translated"] += 1
                logger.debug(f"Deleted old translated audio: {filepath}")
        except Exception as e:
            logger.error(f"Failed to delete {filepath}: {e}")
            stats["errors"] += 1

    stats["total_deleted"] = stats["deleted_original"] + stats["deleted_translated"]
    logger.info(f"Audio cleanup completed: {stats}")

    # Update Prometheus metrics
    if PROMETHEUS_AVAILABLE:
        audio_cleanup_deleted_files_total.labels(directory="original").inc(
            stats["deleted_original"]
        )
        audio_cleanup_deleted_files_total.labels(directory="translated").inc(
            stats["deleted_translated"]
        )

    return stats


def get_disk_usage() -> dict:
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
    ensure_directories()

    stats = {
        "original_bytes": 0,
        "translated_bytes": 0,
        "original_files": 0,
        "translated_files": 0,
    }

    # Count original files
    for filepath in ORIGINAL_AUDIO_DIR.glob("*.wav"):
        try:
            stats["original_bytes"] += filepath.stat().st_size
            stats["original_files"] += 1
        except Exception as e:
            logger.error(f"Failed to stat {filepath}: {e}")

    # Count translated files
    for filepath in TRANSLATED_AUDIO_DIR.glob("*.wav"):
        try:
            stats["translated_bytes"] += filepath.stat().st_size
            stats["translated_files"] += 1
        except Exception as e:
            logger.error(f"Failed to stat {filepath}: {e}")

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
