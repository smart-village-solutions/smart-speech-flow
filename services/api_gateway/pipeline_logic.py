import requests
import logging
import time, psutil
import struct
import io
import wave
import re
import unicodedata
import audioop
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum
import numpy as np
import asyncio
import aiohttp

# Circuit Breaker Integration
from .circuit_breaker import CircuitBreakerOpenException
from .service_health import service_health_manager
from .graceful_degradation import graceful_degradation_manager
from .translation_refiner import RefinementOutcome, translation_refiner

ASR_URL = "http://asr:8000/transcribe"
TRANSLATION_URL = "http://translation:8000/translate"
TTS_URL = "http://tts:8000/synthesize"

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# === Audio Validation Configuration ===

class AudioValidationError(Exception):
    """Custom exception for audio validation errors"""
    pass

@dataclass
class AudioSpecs:
    """Audio specification requirements"""
    MAX_DURATION_SECONDS: float = 200.0  # Maximum 200 seconds
    MAX_FILE_SIZE_MB: float = 32.0       # Maximum 32 MB
    REQUIRED_SAMPLE_RATE: int = 16000   # 16kHz
    REQUIRED_BIT_DEPTH: int = 16        # 16-bit
    REQUIRED_CHANNELS: int = 1          # Mono
    MIN_DURATION_SECONDS: float = 0.1   # Minimum 100ms

# === Text Validation Configuration ===

class TextValidationError(Exception):
    """Custom exception for text validation errors"""
    pass

@dataclass
class TextSpecs:
    """Text specification requirements"""
    MAX_LENGTH: int = 500              # Maximum 500 characters
    MIN_LENGTH: int = 1                # Minimum 1 character
    ALLOWED_ENCODINGS: List[str] = None  # UTF-8 primary

    def __post_init__(self):
        if self.ALLOWED_ENCODINGS is None:
            self.ALLOWED_ENCODINGS = ['utf-8']

@dataclass
class TextValidationResult:
    """Result of text validation"""
    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    # Text properties
    length: Optional[int] = None
    encoding: Optional[str] = None
    contains_spam: Optional[bool] = None
    contains_harmful_content: Optional[bool] = None
    validation_time_ms: Optional[int] = None
    normalized_text: Optional[str] = None

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
            return AudioValidationResult(
                is_valid=False,
                error_code="FILE_TOO_LARGE",
                error_message=f"Audio file too large: {file_size_bytes/1024/1024:.1f}MB. Maximum allowed: {specs.MAX_FILE_SIZE_MB}MB",
                details={
                    "file_size_bytes": file_size_bytes,
                    "max_size_bytes": max_size_bytes,
                    "file_size_mb": round(file_size_bytes/1024/1024, 2)
                },
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Step 2: WAV format validation
        try:
            audio_io = io.BytesIO(audio_bytes)
            with wave.open(audio_io, 'rb') as wav_file:
                # Get WAV properties
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frames = wav_file.getnframes()

                # Calculate duration
                duration_seconds = frames / sample_rate if sample_rate > 0 else 0
                bit_depth = sample_width * 8

        except Exception as e:
            return AudioValidationResult(
                is_valid=False,
                error_code="INVALID_WAV_FORMAT",
                error_message=f"Invalid WAV format: {str(e)}",
                details={"wav_error": str(e)},
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Attempt automatic conversion to required specs if needed
        conversion_attempted = False
        conversion_applied = False
        conversion_error: Optional[str] = None

        if (
            sample_rate != specs.REQUIRED_SAMPLE_RATE or
            bit_depth != specs.REQUIRED_BIT_DEPTH or
            channels != specs.REQUIRED_CHANNELS
        ):
            conversion_attempted = True
            try:
                (audio_bytes,
                 sample_rate,
                 bit_depth,
                 channels,
                 duration_seconds) = convert_audio_to_required_specs(
                    audio_bytes,
                    sample_rate,
                    bit_depth,
                    channels,
                    specs.REQUIRED_SAMPLE_RATE,
                    specs.REQUIRED_BIT_DEPTH,
                    specs.REQUIRED_CHANNELS
                )
                file_size_bytes = len(audio_bytes)
                conversion_applied = True
            except Exception as e:
                conversion_error = str(e)

        # Step 3: Audio specifications validation
        validation_errors = []

        # Sample rate check
        if sample_rate != specs.REQUIRED_SAMPLE_RATE:
            validation_errors.append(f"Sample rate {sample_rate}Hz, required: {specs.REQUIRED_SAMPLE_RATE}Hz")

        # Bit depth check
        if bit_depth != specs.REQUIRED_BIT_DEPTH:
            validation_errors.append(f"Bit depth {bit_depth}-bit, required: {specs.REQUIRED_BIT_DEPTH}-bit")

        # Channels check (Mono)
        if channels != specs.REQUIRED_CHANNELS:
            validation_errors.append(f"Channels {channels}, required: {specs.REQUIRED_CHANNELS} (Mono)")

        # Duration checks
        if duration_seconds < specs.MIN_DURATION_SECONDS:
            validation_errors.append(f"Duration {duration_seconds:.2f}s too short, minimum: {specs.MIN_DURATION_SECONDS}s")

        if duration_seconds > specs.MAX_DURATION_SECONDS:
            validation_errors.append(f"Duration {duration_seconds:.2f}s too long, maximum: {specs.MAX_DURATION_SECONDS}s")

        if validation_errors:
            if conversion_attempted and not conversion_applied and conversion_error:
                validation_errors.append(f"automatic conversion failed: {conversion_error}")
            return AudioValidationResult(
                is_valid=False,
                error_code="INVALID_AUDIO_SPECS",
                error_message=f"Audio specifications invalid: {'; '.join(validation_errors)}",
                details={
                    "current_specs": {
                        "sample_rate": sample_rate,
                        "bit_depth": bit_depth,
                        "channels": channels,
                        "duration_seconds": duration_seconds
                    },
                    "required_specs": {
                        "sample_rate": specs.REQUIRED_SAMPLE_RATE,
                        "bit_depth": specs.REQUIRED_BIT_DEPTH,
                        "channels": specs.REQUIRED_CHANNELS,
                        "min_duration": specs.MIN_DURATION_SECONDS,
                        "max_duration": specs.MAX_DURATION_SECONDS
                    }
                },
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Step 4: Audio normalization (if requested and valid)
        normalization_applied = False
        if normalize:
            try:
                normalized_bytes = normalize_audio(audio_bytes, sample_rate, bit_depth, channels)
                if normalized_bytes != audio_bytes:
                    normalization_applied = True
                    audio_bytes = normalized_bytes
            except Exception as e:
                logging.warning(f"Audio normalization failed: {e}")
                # Normalization failure is not critical - continue with original audio

        # Step 5: Success - all validations passed
        validation_time_ms = int((time.perf_counter() - start_time) * 1000)

        return AudioValidationResult(
            is_valid=True,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            validation_time_ms=validation_time_ms,
            normalization_applied=normalization_applied,
            spec_conversion_applied=conversion_applied,
            processed_audio=audio_bytes
        )

    except Exception as e:
        return AudioValidationResult(
            is_valid=False,
            error_code="VALIDATION_ERROR",
            error_message=f"Audio validation failed: {str(e)}",
            details={"exception": str(e)},
            validation_time_ms=int((time.perf_counter() - start_time) * 1000)
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
        with wave.open(audio_io, 'rb') as wav_file:
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
                audio_float *= (target_level / current_max)

        # Step 3: Basic noise gate (remove very quiet sections)
        noise_threshold = 0.01  # 1% of maximum
        audio_float = np.where(np.abs(audio_float) < noise_threshold, 0, audio_float)

        # Convert back to original bit depth
        audio_normalized = (audio_float * max_val).astype(audio_data.dtype)

        # Write back to WAV format
        output_io = io.BytesIO()
        with wave.open(output_io, 'wb') as wav_output:
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
    bit_depth: int,
    channels: int,
    target_sample_rate: int,
    target_bit_depth: int,
    target_channels: int
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
    with wave.open(audio_io, 'rb') as wav_in:
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
        bit_depth = working_sample_width * 8

    # Convert to mono if needed
    if working_channels != target_channels:
        if working_channels == 2:
            working_frames = audioop.tomono(working_frames, working_sample_width, 0.5, 0.5)
            working_channels = 1
        else:
            raise ValueError(f"Cannot convert {working_channels} channels to mono")
        channels = working_channels

    # Resample if needed
    if sample_rate != target_sample_rate:
        working_frames, _ = audioop.ratecv(
            working_frames,
            working_sample_width,
            working_channels,
            sample_rate,
            target_sample_rate,
            None
        )
        sample_rate = target_sample_rate

    output_io = io.BytesIO()
    with wave.open(output_io, 'wb') as wav_out:
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
        duration_seconds
    )


# === Text Validation and Processing ===

def validate_text_input(text: str, enable_content_filtering: bool = True) -> TextValidationResult:
    """
    Comprehensive text validation and content filtering

    Validates:
    - Text length (1-500 characters)
    - UTF-8 encoding
    - Spam detection
    - Harmful content filtering

    Args:
        text: Input text to validate
        enable_content_filtering: Whether to apply content filtering

    Returns:
        TextValidationResult with validation status and details
    """
    start_time = time.perf_counter()
    specs = TextSpecs()

    try:
        # Step 1: Basic validation
        if not isinstance(text, str):
            return TextValidationResult(
                is_valid=False,
                error_code="INVALID_TYPE",
                error_message="Input must be a string",
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Step 2: Length validation
        text_length = len(text)
        if text_length < specs.MIN_LENGTH:
            return TextValidationResult(
                is_valid=False,
                error_code="TEXT_TOO_SHORT",
                error_message=f"Text too short: {text_length} characters. Minimum: {specs.MIN_LENGTH}",
                details={"length": text_length, "min_length": specs.MIN_LENGTH},
                length=text_length,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        if text_length > specs.MAX_LENGTH:
            return TextValidationResult(
                is_valid=False,
                error_code="TEXT_TOO_LONG",
                error_message=f"Text too long: {text_length} characters. Maximum: {specs.MAX_LENGTH}",
                details={"length": text_length, "max_length": specs.MAX_LENGTH},
                length=text_length,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Step 3: Encoding validation
        try:
            text.encode('utf-8')
            encoding = 'utf-8'
        except UnicodeEncodeError:
            return TextValidationResult(
                is_valid=False,
                error_code="INVALID_ENCODING",
                error_message="Text contains invalid UTF-8 characters",
                details={"encoding_error": "utf-8 encoding failed"},
                length=text_length,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000)
            )

        # Step 4: Text normalization
        normalized_text = normalize_text(text)

        # Step 5: Content filtering (always detect, optionally block)
        contains_spam = detect_spam(normalized_text)
        contains_harmful_content = detect_harmful_content(normalized_text)

        if enable_content_filtering:
            if contains_spam:
                return TextValidationResult(
                    is_valid=False,
                    error_code="SPAM_DETECTED",
                    error_message="Text appears to be spam",
                    details={"spam_patterns": "multiple repetitive patterns detected"},
                    length=text_length,
                    encoding=encoding,
                    contains_spam=True,
                    normalized_text=normalized_text,
                    validation_time_ms=int((time.perf_counter() - start_time) * 1000)
                )

            if contains_harmful_content:
                return TextValidationResult(
                    is_valid=False,
                    error_code="HARMFUL_CONTENT",
                    error_message="Text contains potentially harmful content",
                    details={"content_filter": "harmful patterns detected"},
                    length=text_length,
                    encoding=encoding,
                    contains_harmful_content=True,
                    normalized_text=normalized_text,
                    validation_time_ms=int((time.perf_counter() - start_time) * 1000)
                )

        # Step 6: Success
        return TextValidationResult(
            is_valid=True,
            length=text_length,
            encoding=encoding,
            contains_spam=contains_spam,
            contains_harmful_content=contains_harmful_content,
            normalized_text=normalized_text,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000)
        )

    except Exception as e:
        return TextValidationResult(
            is_valid=False,
            error_code="VALIDATION_ERROR",
            error_message=f"Text validation failed: {str(e)}",
            details={"exception": str(e)},
            validation_time_ms=int((time.perf_counter() - start_time) * 1000)
        )


def normalize_text(text: str) -> str:
    """
    Normalize text for processing

    - Strip whitespace
    - Normalize unicode characters
    - Remove excessive whitespace
    """
    # Strip leading/trailing whitespace
    text = text.strip()

    # Normalize unicode (NFC - canonical composition)
    text = unicodedata.normalize('NFC', text)

    # Replace multiple whitespace with single space
    text = re.sub(r'\s+', ' ', text)

    return text


def detect_spam(text: str) -> bool:
    """
    Simple spam detection

    Detects:
    - Excessive repetition
    - ALL CAPS text
    - Common spam patterns
    """
    # Check for excessive repetition
    words = text.lower().split()
    if len(words) > 3 and len(set(words)) < len(words) * 0.5:
        return True

    # Check for excessive caps (more than 60% uppercase letters)
    letter_chars = [c for c in text if c.isalpha()]
    if len(letter_chars) > 10:
        caps_ratio = len([c for c in letter_chars if c.isupper()]) / len(letter_chars)
        if caps_ratio > 0.6:
            return True

    # Check for common spam patterns
    spam_patterns = [
        r'(.)\1{4,}',  # Same character repeated 5+ times
        r'(..)\1{3,}',  # Same 2-char pattern repeated 4+ times
        r'(?i)(buy now|click here|free money|act now).*\1',  # Common spam phrases repeated
        r'!!!.*!!!.*!!!',  # Multiple exclamation patterns
    ]

    for pattern in spam_patterns:
        if re.search(pattern, text):
            return True

    return False


def detect_harmful_content(text: str) -> bool:
    """
    Basic harmful content detection

    Note: This is a simple implementation.
    In production, use dedicated content moderation APIs.
    """
    # Simple keyword-based filtering
    harmful_patterns = [
        r'(?i)(hate|kill|die|death)\s+(all|every)',
        r'(?i)(bomb|weapon|terror|attack)\s+(plan|how to|instructions|making)',
        r'(?i)(suicide|self\s*harm|hurt\s*myself)',
    ]

    for pattern in harmful_patterns:
        if re.search(pattern, text):
            return True

    return False


def process_text_pipeline(text: str, source_lang: str, target_lang: str, debug: bool = False, validate_text: bool = True) -> Dict[str, Any]:
    """
    Optimized text processing pipeline that skips ASR

    Pipeline: Text Input → Text Validation → Translation → TTS

    Args:
        text: Input text to process
        source_lang: Source language code
        target_lang: Target language code
        debug: Enable debug information
        validate_text: Enable text validation

    Returns:
        Processing result with translation and audio
    """
    debug_info = {
        "frontend_input": {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "text_length": len(text)
        },
        "steps": []
    }
    start_total = time.perf_counter()

    try:
        # Step 1: Text validation (if enabled)
        if validate_text:
            start_validation = time.perf_counter()
            validation_result = validate_text_input(text, enable_content_filtering=True)

            debug_info["steps"].append({
                "step": "Text_Validation",
                "input": {"text_length": len(text), "enable_filtering": True},
                "output": validation_result.is_valid,
                "error": None if validation_result.is_valid else validation_result.error_message,
                "duration": round(time.perf_counter() - start_validation, 3)
            })

            if not validation_result.is_valid:
                debug_info["error"] = f"Text validation failed: {validation_result.error_message}"
                debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
                debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

                return {
                    "error": True,
                    "error_msg": f"Text validation failed: {validation_result.error_message}",
                    "validation_result": validation_result,
                    "asr_text": None,
                    "translation_text": None,
                    "audio_bytes": None,
                    "debug": debug_info
                }

            # Use normalized text for processing
            processed_text = validation_result.normalized_text
        else:
            processed_text = text

        # Step 2: Translation (skip ASR entirely)
        start_translation = time.perf_counter()
        translation_payload = {
            "text": processed_text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model": "m2m100_1.2B",
            "debug": str(debug).lower()
        }

        translation_resp = requests.post(TRANSLATION_URL, json=translation_payload)
        translation_json = translation_resp.json()
        translation_text = translation_json.get("translations", "")
        tts_text = translation_json.get("tts_text")

        debug_info["steps"].append({
            "step": "Translation",
            "input": translation_payload,
            "output": translation_text,
            "error": translation_json.get("error"),
            "duration": round(time.perf_counter() - start_translation, 3)
        })

        # Translation error handling
        if translation_resp.status_code != 200:
            error_msg = translation_json.get("detail") or str(translation_json)
            debug_info["error"] = f"Translation-Fehler: {error_msg}"
            debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
            debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

            return {
                "error": True,
                "error_msg": f"Translation-Fehler: {error_msg}",
                "asr_text": processed_text,  # Original text as "ASR" result
                "translation_text": None,
                "audio_bytes": None,
                "debug": debug_info
            }

        # Optional LLM refinement
        refined_tts_text = tts_text
        if translation_refiner.is_active:
            refinement_context = {
                "original_text": processed_text,
                "pipeline": "text",
            }
            outcome: RefinementOutcome = translation_refiner.refine(
                translation_text,
                source_lang,
                target_lang,
                context=refinement_context,
            )
            translation_text = outcome.text
            if outcome.changed:
                # Drop precomputed romanization so TTS uses refined text directly
                refined_tts_text = None

            debug_info["steps"].append({
                "step": "LLM_Refinement",
                "input": {"enabled": True, "changed": outcome.changed},
                "output": translation_text,
                "error": outcome.error,
                "duration": round((outcome.latency_ms or 0.0) / 1000, 3),
            })

        # Step 3: TTS
        start_tts = time.perf_counter()
        tts_payload = {"text": translation_text, "lang": target_lang, "debug": str(debug).lower()}
        if refined_tts_text:
            tts_payload["tts_text"] = refined_tts_text

        tts_resp = requests.post(TTS_URL, json=tts_payload)

        if tts_resp.status_code != 200 or tts_resp.headers.get("content-type", "") != "audio/wav":
            try:
                tts_json = tts_resp.json()
                error_msg = tts_json.get("error") or str(tts_json)
            except Exception:
                error_msg = tts_resp.text

            debug_info["steps"].append({
                "step": "TTS",
                "input": {"lang": target_lang, "text": translation_text},
                "output": None,
                "error": error_msg,
                "duration": round(time.perf_counter() - start_tts, 3)
            })
            debug_info["error"] = f"TTS-Fehler: {error_msg}"
            debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
            debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

            return {
                "error": True,
                "error_msg": f"TTS-Fehler: {error_msg}",
                "asr_text": processed_text,
                "translation_text": translation_text,
                "audio_bytes": None,
                "debug": debug_info
            }

        audio_bytes = tts_resp.content
        debug_info["steps"].append({
            "step": "TTS",
            "input": {"lang": target_lang, "text": translation_text},
            "output": "audio/wav",
            "error": None,
            "duration": round(time.perf_counter() - start_tts, 3)
        })

        # Success
        debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
        debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

        return {
            "error": False,
            "asr_text": processed_text,  # Original/normalized text as "ASR" result
            "translation_text": translation_text,
            "audio_bytes": audio_bytes,
            "debug": debug_info
        }

    except Exception as e:
        debug_info["error"] = f"Pipeline-Fehler: {str(e)}"
        debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
        debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

        return {
            "error": True,
            "error_msg": f"Pipeline-Fehler: {str(e)}",
            "asr_text": None,
            "translation_text": None,
            "audio_bytes": None,
            "debug": debug_info
        }


def process_wav(file_bytes, source_lang, target_lang, debug=False, validate_audio=True):
    """
    Enhanced WAV processing with optional audio validation

    Args:
        file_bytes: Raw audio file bytes
        source_lang: Source language code
        target_lang: Target language code
        debug: Enable debug information
        validate_audio: Enable comprehensive audio validation

    Returns:
        Dict with processing results including validation info
    """
    debug_info = {"frontend_input": {"source_lang": source_lang, "target_lang": target_lang, "file_size": len(file_bytes)}, "steps": []}
    start_total = time.perf_counter()

    # Audio Validation Step (if enabled)
    if validate_audio:
        start_validation = time.perf_counter()
        original_file_size = len(file_bytes)
        validation_result = validate_audio_input(file_bytes, normalize=True)

        if validation_result.is_valid and validation_result.processed_audio:
            file_bytes = validation_result.processed_audio

        validation_step = {
            "step": "Audio_Validation",
            "input": {"file_size": original_file_size},
            "output": validation_result.is_valid,
            "error": None if validation_result.is_valid else validation_result.error_message,
            "duration": round(time.perf_counter() - start_validation, 3),
            "details": {
                "validation_time_ms": validation_result.validation_time_ms,
                "normalization_applied": validation_result.normalization_applied,
                "spec_conversion_applied": validation_result.spec_conversion_applied
            }
        }

        if validation_result.is_valid:
            validation_step["details"].update({
                "duration_seconds": validation_result.duration_seconds,
                "sample_rate": validation_result.sample_rate,
                "bit_depth": validation_result.bit_depth,
                "channels": validation_result.channels,
                "processed_file_size": len(file_bytes)
            })
        else:
            validation_step["details"]["error_code"] = validation_result.error_code
            validation_step["details"]["error_details"] = validation_result.details

        debug_info["steps"].append(validation_step)

        # Return early if validation failed
        if not validation_result.is_valid:
            debug_info["error"] = f"Audio validation failed: {validation_result.error_message}"
            debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
            debug_info["total_duration"] = round(time.perf_counter() - start_total, 3)

            return {
                "error": True,
                "error_msg": f"Audio validation failed: {validation_result.error_message}",
                "validation_result": validation_result,
                "asr_text": None,
                "translation_text": None,
                "audio_bytes": None,
                "debug": debug_info
            }

    # ASR
    start_asr = time.perf_counter()
    asr_resp = requests.post(ASR_URL, files={"file": ("input.wav", file_bytes, "audio/wav")}, data={"lang": source_lang, "debug": str(debug).lower()})
    asr_json = asr_resp.json()
    asr_text = asr_json.get("text", "")
    debug_info["steps"].append({"step": "ASR", "input": {"lang": source_lang}, "output": asr_text, "error": asr_json.get("error"), "duration": round(time.perf_counter()-start_asr,3)})
    # Translation
    start_trans = time.perf_counter()
    translation_payload = {
        "text": asr_text,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": "m2m100_1.2B",
        "debug": str(debug).lower()
    }
    translation_resp = requests.post(TRANSLATION_URL, json=translation_payload)
    translation_json = translation_resp.json()
    translation_text = translation_json.get("translations", "")
    debug_info["steps"].append({"step": "Translation", "input": translation_payload, "output": translation_text, "error": translation_json.get("error"), "duration": round(time.perf_counter()-start_trans,3)})
    # Fehlerbehandlung
    if translation_resp.status_code != 200:
        error_msg = translation_json.get("detail") or str(translation_json)
        debug_info["error"] = f"Translation-Fehler: {error_msg}"
        debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
        debug_info["total_duration"] = round(time.perf_counter()-start_total,3)
        return {
            "error": True,
            "error_msg": f"Translation-Fehler: {error_msg}",
            "asr_text": asr_text,
            "translation_text": None,
            "audio_bytes": None,
            "debug": debug_info
        }
    # Optional LLM refinement
    if translation_refiner.is_active:
        outcome = translation_refiner.refine(
            translation_text,
            source_lang,
            target_lang,
            context={"original_text": asr_text, "pipeline": "audio"},
        )
        translation_text = outcome.text
        debug_info["steps"].append({
            "step": "LLM_Refinement",
            "input": {"enabled": True, "changed": outcome.changed},
            "output": translation_text,
            "error": outcome.error,
            "duration": round((outcome.latency_ms or 0.0) / 1000, 3),
        })
    # TTS
    start_tts = time.perf_counter()
    tts_resp = requests.post(TTS_URL, json={"text": translation_text, "lang": target_lang, "debug": str(debug).lower()})
    if tts_resp.status_code != 200 or tts_resp.headers.get("content-type","") != "audio/wav":
        try:
            tts_json = tts_resp.json()
            error_msg = tts_json.get("error") or str(tts_json)
        except Exception:
            error_msg = tts_resp.text
        debug_info["steps"].append({"step": "TTS", "input": {"lang": target_lang, "text": translation_text}, "output": None, "error": error_msg, "duration": round(time.perf_counter()-start_tts,3)})
        debug_info["error"] = f"TTS-Fehler: {error_msg}"
        debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
        debug_info["total_duration"] = round(time.perf_counter()-start_total,3)
        return {
            "error": True,
            "error_msg": f"TTS-Fehler: {error_msg}",
            "asr_text": asr_text,
            "translation_text": translation_text,
            "audio_bytes": None,
            "debug": debug_info
        }
    audio_bytes = tts_resp.content
    debug_info["steps"].append({"step": "TTS", "input": {"lang": target_lang, "text": translation_text}, "output": "audio/wav", "error": None, "duration": round(time.perf_counter()-start_tts,3)})
    debug_info["system"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
    debug_info["total_duration"] = round(time.perf_counter()-start_total,3)
    return {
        "error": False,
        "asr_text": asr_text,
        "translation_text": translation_text,
        "audio_bytes": audio_bytes,
        "debug": debug_info
    }

async def process_wav_for_session(file, source_lang, target_lang, session_id=None):
    """
    Erweiterte Pipeline-Funktion mit Session-Support
    Nutzt die bestehende process_wav-Logik
    """
    # Rufe bestehende Funktion auf
    result = await process_wav(file, source_lang, target_lang)

    # Zusätzliche Session-Logik (falls gewünscht)
    if session_id:
        # Hier könnten zusätzliche Session-spezifische Verarbeitungen stehen
        pass

    return result
