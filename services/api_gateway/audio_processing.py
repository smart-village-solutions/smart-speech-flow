"""WAV validation and conversion to the format the ASR service expects.

The only production module that imports `audioop`, which Python 3.13 removes.
"""

import audioop
import io
import logging
import time
import wave
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# === Audio Validation Configuration ===


class AudioValidationError(Exception):
    """Custom exception for audio validation errors"""

    pass


@dataclass
class AudioSpecs:
    """Audio specification requirements"""

    MAX_DURATION_SECONDS: float = 200.0  # Maximum 200 seconds
    MAX_FILE_SIZE_MB: float = 32.0  # Maximum 32 MB
    REQUIRED_SAMPLE_RATE: int = 16000  # 16kHz
    REQUIRED_BIT_DEPTH: int = 16  # 16-bit
    REQUIRED_CHANNELS: int = 1  # Mono
    MIN_DURATION_SECONDS: float = 0.1  # Minimum 100ms


@dataclass
class AudioValidationResult:
    """Result of audio validation"""

    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    # Audio properties (if valid)
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None
    channels: Optional[int] = None

    # Performance metrics
    validation_time_ms: Optional[int] = None
    normalization_applied: bool = False
    spec_conversion_applied: bool = False
    processed_audio: Optional[bytes] = None


def _validation_time_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


def _build_audio_validation_failure(
    *,
    start_time: float,
    error_code: str,
    error_message: str,
    details: Dict[str, Any],
) -> AudioValidationResult:
    return AudioValidationResult(
        is_valid=False,
        error_code=error_code,
        error_message=error_message,
        details=details,
        validation_time_ms=_validation_time_ms(start_time),
    )


def build_file_too_large_result(
    *, file_size_bytes: int, max_size_bytes: int, specs: AudioSpecs, start_time: float
) -> AudioValidationResult:
    """Build the consistent file-size validation failure used by both validators."""
    return _build_audio_validation_failure(
        start_time=start_time,
        error_code="FILE_TOO_LARGE",
        error_message=(
            f"Audio file too large: {file_size_bytes / 1024 / 1024:.1f}MB. "
            f"Maximum allowed: {specs.MAX_FILE_SIZE_MB}MB"
        ),
        details={
            "file_size_bytes": file_size_bytes,
            "max_size_bytes": max_size_bytes,
            "file_size_mb": round(file_size_bytes / 1024 / 1024, 2),
        },
    )


def _read_wav_properties(
    audio_bytes: bytes, start_time: float
) -> AudioValidationResult | Tuple[int, int, int, float]:
    try:
        audio_io = io.BytesIO(audio_bytes)
        with wave.open(audio_io, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.getnframes()
            duration_seconds = frames / sample_rate if sample_rate > 0 else 0
            bit_depth = sample_width * 8
        return channels, bit_depth, sample_rate, duration_seconds
    except Exception as exc:
        return _build_audio_validation_failure(
            start_time=start_time,
            error_code="INVALID_WAV_FORMAT",
            error_message=f"Invalid WAV format: {str(exc)}",
            details={"wav_error": str(exc)},
        )


def _convert_audio_if_needed(
    audio_bytes: bytes,
    *,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    duration_seconds: float,
    specs: AudioSpecs,
) -> Tuple[bytes, int, int, int, float, bool, bool, Optional[str]]:
    conversion_attempted = False
    conversion_applied = False
    conversion_error: Optional[str] = None

    if (
        sample_rate == specs.REQUIRED_SAMPLE_RATE
        and bit_depth == specs.REQUIRED_BIT_DEPTH
        and channels == specs.REQUIRED_CHANNELS
    ):
        return (
            audio_bytes,
            sample_rate,
            bit_depth,
            channels,
            duration_seconds,
            conversion_attempted,
            conversion_applied,
            conversion_error,
        )

    conversion_attempted = True
    try:
        (
            audio_bytes,
            sample_rate,
            bit_depth,
            channels,
            duration_seconds,
        ) = convert_audio_to_required_specs(
            audio_bytes,
            sample_rate,
            channels,
            specs.REQUIRED_SAMPLE_RATE,
            specs.REQUIRED_BIT_DEPTH,
            specs.REQUIRED_CHANNELS,
        )
        conversion_applied = True
    except Exception as exc:
        conversion_error = str(exc)

    return (
        audio_bytes,
        sample_rate,
        bit_depth,
        channels,
        duration_seconds,
        conversion_attempted,
        conversion_applied,
        conversion_error,
    )


def _collect_audio_validation_errors(
    *,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    duration_seconds: float,
    specs: AudioSpecs,
    conversion_attempted: bool,
    conversion_applied: bool,
    conversion_error: Optional[str],
) -> List[str]:
    validation_errors = []

    if sample_rate != specs.REQUIRED_SAMPLE_RATE:
        validation_errors.append(
            f"Sample rate {sample_rate}Hz, required: {specs.REQUIRED_SAMPLE_RATE}Hz"
        )
    if bit_depth != specs.REQUIRED_BIT_DEPTH:
        validation_errors.append(
            f"Bit depth {bit_depth}-bit, required: {specs.REQUIRED_BIT_DEPTH}-bit"
        )
    if channels != specs.REQUIRED_CHANNELS:
        validation_errors.append(f"Channels {channels}, required: {specs.REQUIRED_CHANNELS} (Mono)")
    if duration_seconds < specs.MIN_DURATION_SECONDS:
        validation_errors.append(
            f"Duration {duration_seconds:.2f}s too short, minimum: {specs.MIN_DURATION_SECONDS}s"
        )
    if duration_seconds > specs.MAX_DURATION_SECONDS:
        validation_errors.append(
            f"Duration {duration_seconds:.2f}s too long, maximum: {specs.MAX_DURATION_SECONDS}s"
        )
    if conversion_attempted and not conversion_applied and conversion_error:
        validation_errors.append(f"automatic conversion failed: {conversion_error}")

    return validation_errors


def _normalize_audio_if_requested(
    audio_bytes: bytes,
    *,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    normalize: bool,
) -> Tuple[bytes, bool]:
    if not normalize:
        return audio_bytes, False

    try:
        normalized_bytes = normalize_audio(audio_bytes, sample_rate, bit_depth, channels)
        if normalized_bytes != audio_bytes:
            return normalized_bytes, True
    except Exception as exc:
        logging.warning(f"Audio normalization failed: {exc}")

    return audio_bytes, False


# === Audio Validation Functions ===


def validate_audio_input(audio_bytes: bytes, normalize: bool = True) -> AudioValidationResult:
    """
    Comprehensive audio validation and normalization

    Validates:
    - WAV format (16kHz, 16-bit, Mono)
    - Duration limits (0.1s - 200s)
    - File size limits (max 32 MB)
    - Audio quality and integrity

    Args:
        audio_bytes: Raw audio file bytes
        normalize: Whether to apply audio normalization

    Returns:
        AudioValidationResult with validation status and details
    """
    start_time = time.perf_counter()
    specs = AudioSpecs()

    try:
        # Step 1: File size validation
        file_size_bytes = len(audio_bytes)
        max_size_bytes = int(specs.MAX_FILE_SIZE_MB * 1024 * 1024)

        if file_size_bytes > max_size_bytes:
            return build_file_too_large_result(
                file_size_bytes=file_size_bytes,
                max_size_bytes=max_size_bytes,
                specs=specs,
                start_time=start_time,
            )

        wav_properties = _read_wav_properties(audio_bytes, start_time)
        if isinstance(wav_properties, AudioValidationResult):
            return wav_properties
        channels, bit_depth, sample_rate, duration_seconds = wav_properties

        (
            audio_bytes,
            sample_rate,
            bit_depth,
            channels,
            duration_seconds,
            conversion_attempted,
            conversion_applied,
            conversion_error,
        ) = _convert_audio_if_needed(
            audio_bytes,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            duration_seconds=duration_seconds,
            specs=specs,
        )
        file_size_bytes = len(audio_bytes)

        validation_errors = _collect_audio_validation_errors(
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            duration_seconds=duration_seconds,
            specs=specs,
            conversion_attempted=conversion_attempted,
            conversion_applied=conversion_applied,
            conversion_error=conversion_error,
        )
        if validation_errors:
            return AudioValidationResult(
                is_valid=False,
                error_code="INVALID_AUDIO_SPECS",
                error_message=f"Audio specifications invalid: {'; '.join(validation_errors)}",
                details={
                    "current_specs": {
                        "sample_rate": sample_rate,
                        "bit_depth": bit_depth,
                        "channels": channels,
                        "duration_seconds": duration_seconds,
                    },
                    "required_specs": {
                        "sample_rate": specs.REQUIRED_SAMPLE_RATE,
                        "bit_depth": specs.REQUIRED_BIT_DEPTH,
                        "channels": specs.REQUIRED_CHANNELS,
                        "min_duration": specs.MIN_DURATION_SECONDS,
                        "max_duration": specs.MAX_DURATION_SECONDS,
                    },
                },
                validation_time_ms=_validation_time_ms(start_time),
            )

        audio_bytes, normalization_applied = _normalize_audio_if_requested(
            audio_bytes,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            normalize=normalize,
        )

        return AudioValidationResult(
            is_valid=True,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            validation_time_ms=_validation_time_ms(start_time),
            normalization_applied=normalization_applied,
            spec_conversion_applied=conversion_applied,
            processed_audio=audio_bytes,
        )

    except Exception as e:
        return AudioValidationResult(
            is_valid=False,
            error_code="VALIDATION_ERROR",
            error_message=f"Audio validation failed: {str(e)}",
            details={"exception": str(e)},
            validation_time_ms=_validation_time_ms(start_time),
        )


def normalize_audio(audio_bytes: bytes, sample_rate: int, bit_depth: int, channels: int) -> bytes:
    """
    Normalize audio for optimal ASR processing

    Applies:
    - Volume normalization (prevent clipping/too quiet)
    - DC offset removal
    - Basic noise gate for very quiet sections

    Args:
        audio_bytes: Raw WAV audio bytes
        sample_rate: Audio sample rate
        bit_depth: Audio bit depth
        channels: Number of channels

    Returns:
        Normalized audio bytes
    """
    try:
        # Read audio data
        audio_io = io.BytesIO(audio_bytes)
        with wave.open(audio_io, "rb") as wav_file:
            frames = wav_file.readframes(-1)

        # Convert to numpy array based on bit depth
        if bit_depth == 16:
            audio_data = np.frombuffer(frames, dtype=np.int16)
            max_val = 32767.0
        elif bit_depth == 24:
            # 24-bit is more complex, convert to 32-bit first
            audio_data = np.frombuffer(frames, dtype=np.int32)
            max_val = 8388607.0
        elif bit_depth == 32:
            audio_data = np.frombuffer(frames, dtype=np.int32)
            max_val = 2147483647.0
        else:
            # Unsupported bit depth, return original
            return audio_bytes

        # Convert to float for processing
        audio_float = audio_data.astype(np.float32) / max_val

        # Step 1: DC offset removal
        audio_float = audio_float - np.mean(audio_float)

        # Step 2: Volume normalization
        current_max = np.max(np.abs(audio_float))
        if current_max > 0:
            # Target 90% of maximum to prevent clipping
            target_level = 0.9
            if current_max < target_level:
                # Boost quiet audio
                normalization_factor = min(target_level / current_max, 3.0)  # Max 3x boost
                audio_float *= normalization_factor
            elif current_max > target_level:
                # Reduce loud audio
                audio_float *= target_level / current_max

        # Step 3: Basic noise gate (remove very quiet sections)
        noise_threshold = 0.01  # 1% of maximum
        audio_float = np.where(np.abs(audio_float) < noise_threshold, 0, audio_float)

        # Convert back to original bit depth
        audio_normalized = (audio_float * max_val).astype(audio_data.dtype)

        # Write back to WAV format
        output_io = io.BytesIO()
        with wave.open(output_io, "wb") as wav_output:
            wav_output.setnchannels(channels)
            wav_output.setsampwidth(bit_depth // 8)
            wav_output.setframerate(sample_rate)
            wav_output.writeframes(audio_normalized.tobytes())

        return output_io.getvalue()

    except Exception as e:
        logging.warning(f"Audio normalization failed: {e}")
        # Return original audio if normalization fails
        return audio_bytes


def convert_audio_to_required_specs(
    audio_bytes: bytes,
    sample_rate: int,
    channels: int,
    target_sample_rate: int,
    target_bit_depth: int,
    target_channels: int,
) -> Tuple[bytes, int, int, int, float]:
    """
    Convert incoming WAV audio to required specifications using pure Python helpers.
    """

    if target_channels != 1:
        raise ValueError("Only mono output is supported")

    target_sample_width = target_bit_depth // 8
    if target_sample_width not in (1, 2, 3, 4):
        raise ValueError("Unsupported target bit depth")

    audio_io = io.BytesIO(audio_bytes)
    with wave.open(audio_io, "rb") as wav_in:
        frames = wav_in.readframes(-1)
        sample_width = wav_in.getsampwidth()

    if sample_width not in (1, 2, 3, 4):
        raise ValueError("Unsupported source bit depth")

    working_frames = frames
    working_channels = channels
    working_sample_width = sample_width

    # Convert bit depth first if required
    if working_sample_width != target_sample_width:
        working_frames = audioop.lin2lin(working_frames, working_sample_width, target_sample_width)
        working_sample_width = target_sample_width

    # Convert to mono if needed
    if working_channels != target_channels:
        if working_channels == 2:
            working_frames = audioop.tomono(working_frames, working_sample_width, 0.5, 0.5)
            working_channels = 1
        else:
            raise ValueError(f"Cannot convert {working_channels} channels to mono")

    # Resample if needed
    if sample_rate != target_sample_rate:
        working_frames, _ = audioop.ratecv(
            working_frames,
            working_sample_width,
            working_channels,
            sample_rate,
            target_sample_rate,
            None,
        )
        sample_rate = target_sample_rate

    output_io = io.BytesIO()
    with wave.open(output_io, "wb") as wav_out:
        wav_out.setnchannels(working_channels)
        wav_out.setsampwidth(working_sample_width)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(working_frames)

    sample_count = len(working_frames) // (working_sample_width * working_channels)
    duration_seconds = sample_count / sample_rate if sample_rate > 0 else 0.0

    return (
        output_io.getvalue(),
        sample_rate,
        working_sample_width * 8,
        working_channels,
        duration_seconds,
    )
