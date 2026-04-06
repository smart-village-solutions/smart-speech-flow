"""
Enhanced Audio Format Support for Smart Speech Flow Backend
Unterstützt WebM, MP4, MP3, OGG und andere Browser-generierte Formate
"""

import io
import logging
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

from services.api_gateway.pipeline_logic import AudioSpecs, AudioValidationResult


@dataclass
class AudioFormatDetection:
    """Erkannte Audio-Format-Eigenschaften"""

    format_name: str
    mime_type: str
    is_wav: bool
    is_supported_by_browser: bool
    needs_conversion: bool
    confidence: float


class EnhancedAudioValidator:
    """Erweiterte Audio-Validierung mit Multi-Format-Support"""

    SUPPORTED_FORMATS = {
        "wav": {"mime_types": ["audio/wav", "audio/wave"], "confidence": 1.0},
        "webm": {"mime_types": ["audio/webm"], "confidence": 0.9},
        "mp4": {"mime_types": ["audio/mp4", "audio/aac"], "confidence": 0.9},
        "mp3": {"mime_types": ["audio/mpeg"], "confidence": 0.8},
        "ogg": {"mime_types": ["audio/ogg"], "confidence": 0.8},
        "flac": {"mime_types": ["audio/flac"], "confidence": 0.7},
    }

    WAV_SIGNATURES = [
        b"RIFF",  # Standard WAV
        b"RF64",  # WAV mit erweiterter Größe
        b"WAVE",  # WAV-Subformat
    ]

    BROWSER_FORMATS = {
        b"webm": "webm",
        b"\x00\x00\x00\x20ftypmp4": "mp4",
        b"\x00\x00\x00\x1cftypmp4": "mp4",
        b"ID3": "mp3",
        b"\xFF\xFB": "mp3",
        b"\xFF\xF3": "mp3",
        b"\xFF\xF2": "mp3",
        b"OggS": "ogg",
        b"fLaC": "flac",
    }

    def __init__(self):
        self.ffmpeg_available = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        """Prüfe ob FFmpeg verfügbar ist für Format-Konvertierung"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("FFmpeg nicht verfügbar - Fallback auf wave-only")
            return False

    def detect_audio_format(self, audio_bytes: bytes) -> AudioFormatDetection:
        """Detektiere Audio-Format basierend auf Magic Bytes"""

        if len(audio_bytes) < 12:
            return AudioFormatDetection(
                format_name="unknown",
                mime_type="application/octet-stream",
                is_wav=False,
                is_supported_by_browser=False,
                needs_conversion=True,
                confidence=0.0,
            )

        # WAV-Format prüfen
        header = audio_bytes[:12]
        if any(header.startswith(sig) for sig in self.WAV_SIGNATURES):
            # Zusätzliche WAV-Validierung
            if b"WAVE" in header or b"RIFF" in header[:4]:
                return AudioFormatDetection(
                    format_name="wav",
                    mime_type="audio/wav",
                    is_wav=True,
                    is_supported_by_browser=True,
                    needs_conversion=False,
                    confidence=1.0,
                )

        # Browser-generierte Formate prüfen
        for signature, format_name in self.BROWSER_FORMATS.items():
            if (
                audio_bytes[: len(signature)] == signature
                or signature in audio_bytes[:100]
            ):
                format_info = self.SUPPORTED_FORMATS.get(format_name, {})
                return AudioFormatDetection(
                    format_name=format_name,
                    mime_type=format_info.get(
                        "mime_types", ["application/octet-stream"]
                    )[0],
                    is_wav=False,
                    is_supported_by_browser=True,
                    needs_conversion=True,
                    confidence=format_info.get("confidence", 0.5),
                )

        # WebM spezielle Erkennung (oft von MediaRecorder generiert)
        if b"\x1a\x45\xdf\xa3" in audio_bytes[:100]:  # EBML Header
            return AudioFormatDetection(
                format_name="webm",
                mime_type="audio/webm",
                is_wav=False,
                is_supported_by_browser=True,
                needs_conversion=True,
                confidence=0.9,
            )

        return AudioFormatDetection(
            format_name="unknown",
            mime_type="application/octet-stream",
            is_wav=False,
            is_supported_by_browser=False,
            needs_conversion=True,
            confidence=0.1,
        )

    def validate_and_convert_audio(
        self, audio_bytes: bytes
    ) -> Tuple[bool, bytes, str, dict]:
        """
        Validiere Audio und konvertiere zu WAV wenn nötig

        Returns:
            (success, converted_audio_bytes, error_message, details)
        """

        # 1. Format-Erkennung
        format_detection = self.detect_audio_format(audio_bytes)

        details = {
            "original_format": format_detection.format_name,
            "mime_type": format_detection.mime_type,
            "confidence": format_detection.confidence,
            "conversion_attempted": False,
            "conversion_method": None,
            "original_size_bytes": len(audio_bytes),
        }

        logger.info(
            f"Audio-Format erkannt: {format_detection.format_name} (Konfidenz: {format_detection.confidence})"
        )

        # 2. Wenn bereits WAV, verwende ursprüngliche Validierung
        if format_detection.is_wav:
            try:
                # Teste WAV-Parsing
                audio_io = io.BytesIO(audio_bytes)
                with wave.open(audio_io, "rb") as wav_file:
                    channels = wav_file.getnchannels()
                    sample_rate = wav_file.getframerate()
                    frames = wav_file.getnframes()

                details.update(
                    {
                        "channels": channels,
                        "sample_rate": sample_rate,
                        "frames": frames,
                        "duration_seconds": (
                            frames / sample_rate if sample_rate > 0 else 0
                        ),
                    }
                )

                return True, audio_bytes, "", details

            except Exception as wav_error:
                details["wav_error"] = str(wav_error)
                logger.warning(f"WAV-Parsing fehlgeschlagen: {wav_error}")
                # Fall through zu Konvertierung

        # 3. Browser-Format zu WAV konvertieren
        if format_detection.is_supported_by_browser and self.ffmpeg_available:
            try:
                converted_audio = self._convert_with_ffmpeg(
                    audio_bytes, format_detection.format_name
                )
                if converted_audio:
                    details.update(
                        {
                            "conversion_attempted": True,
                            "conversion_method": "ffmpeg",
                            "converted_size_bytes": len(converted_audio),
                        }
                    )

                    # Validiere konvertiertes WAV
                    try:
                        audio_io = io.BytesIO(converted_audio)
                        with wave.open(audio_io, "rb") as wav_file:
                            details.update(
                                {
                                    "channels": wav_file.getnchannels(),
                                    "sample_rate": wav_file.getframerate(),
                                    "frames": wav_file.getnframes(),
                                }
                            )

                        logger.info(
                            f"Erfolgreiche Konvertierung: {format_detection.format_name} -> WAV"
                        )
                        return True, converted_audio, "", details

                    except Exception as conv_wav_error:
                        details["conversion_wav_error"] = str(conv_wav_error)
                        logger.error(
                            f"Konvertierte WAV-Datei ungültig: {conv_wav_error}"
                        )

            except Exception as conv_error:
                details["conversion_error"] = str(conv_error)
                logger.error(f"FFmpeg-Konvertierung fehlgeschlagen: {conv_error}")

        # 4. Fallback für unbekannte/nicht-unterstützte Formate
        error_message = self._generate_error_message(format_detection, details)
        return False, audio_bytes, error_message, details

    def _convert_with_ffmpeg(
        self, audio_bytes: bytes, source_format: str
    ) -> Optional[bytes]:
        """Konvertiere Audio zu 16kHz, 16-bit, Mono WAV mit FFmpeg"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_input = os.path.join(temp_dir, f"input.{source_format}")
                temp_output = os.path.join(temp_dir, "converted.wav")

                with open(temp_input, "wb") as temp_in:
                    temp_in.write(audio_bytes)

                cmd = [
                    "ffmpeg",
                    "-i",
                    temp_input,
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-sample_fmt",
                    "s16",
                    "-f",
                    "wav",
                    "-y",
                    temp_output,
                ]

                result = subprocess.run(cmd, capture_output=True, timeout=30)

                if result.returncode == 0 and os.path.exists(temp_output):
                    with open(temp_output, "rb") as f:
                        converted_audio = f.read()

                    logger.info(
                        "FFmpeg-Konvertierung erfolgreich: %s -> %s bytes",
                        len(audio_bytes),
                        len(converted_audio),
                    )
                    return converted_audio

                logger.error(
                    "FFmpeg-Fehler (Code %s): %s",
                    result.returncode,
                    result.stderr.decode(),
                )
                return None

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg-Konvertierung Timeout")
            return None
        except Exception as e:
            logger.error(f"FFmpeg-Konvertierung Fehler: {e}")
            return None

    def _generate_error_message(
        self, format_detection: AudioFormatDetection, details: dict
    ) -> str:
        """Generiere benutzerfreundliche Fehlermeldung"""

        if format_detection.format_name == "unknown":
            return (
                "Unbekanntes Audio-Format. Bitte verwenden Sie WAV, WebM, MP4, MP3 oder OGG. "
                "Stellen Sie sicher, dass es sich um eine gültige Audio-Datei handelt."
            )

        if format_detection.is_supported_by_browser:
            if not self.ffmpeg_available:
                return (
                    f"Audio-Format '{format_detection.format_name}' erkannt, aber Konvertierung nicht verfügbar. "
                    f"Bitte konvertieren Sie die Datei zu WAV-Format oder installieren Sie FFmpeg auf dem Server."
                )
            else:
                return (
                    f"Audio-Format '{format_detection.format_name}' konnte nicht zu WAV konvertiert werden. "
                    f"Details: {details.get('conversion_error', 'Unbekannter Konvertierungsfehler')}"
                )

        return (
            f"Audio-Format '{format_detection.format_name}' wird nicht unterstützt. "
            f"Unterstützte Formate: WAV, WebM, MP4, MP3, OGG."
        )


# Integration in bestehende validate_audio_input Funktion
def enhanced_validate_audio_input(
    audio_bytes: bytes, normalize: bool = True
) -> "AudioValidationResult":
    """
    Erweiterte Audio-Validierung mit Multi-Format-Support
    Drop-in Replacement für validate_audio_input
    """
    import time

    start_time = time.perf_counter()
    specs = AudioSpecs()

    # 1. Dateigröße prüfen
    file_size_bytes = len(audio_bytes)
    max_size_bytes = int(specs.MAX_FILE_SIZE_MB * 1024 * 1024)

    if file_size_bytes > max_size_bytes:
        return AudioValidationResult(
            is_valid=False,
            error_code="FILE_TOO_LARGE",
            error_message=f"Audio file too large: {file_size_bytes / 1024 / 1024:.1f}MB. Maximum allowed: {specs.MAX_FILE_SIZE_MB}MB",
            details={
                "file_size_bytes": file_size_bytes,
                "max_size_bytes": max_size_bytes,
                "file_size_mb": round(file_size_bytes / 1024 / 1024, 2),
            },
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # 2. Enhanced Format Detection & Conversion
    validator = EnhancedAudioValidator()
    success, converted_audio, error_message, format_details = (
        validator.validate_and_convert_audio(audio_bytes)
    )

    if not success:
        return AudioValidationResult(
            is_valid=False,
            error_code="INVALID_AUDIO_FORMAT",
            error_message=error_message,
            details={
                "validation_details": format_details,
                "supported_formats": list(validator.SUPPORTED_FORMATS.keys()),
                "ffmpeg_available": validator.ffmpeg_available,
            },
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # 3. Verwende konvertierte Audio-Daten für weitere Validierung
    audio_bytes = converted_audio

    # 4. WAV-Eigenschaften aus Details oder erneut parsen
    try:
        if "channels" in format_details:
            channels = format_details["channels"]
            sample_rate = format_details["sample_rate"]
            frames = format_details["frames"]
            duration_seconds = format_details.get(
                "duration_seconds", frames / sample_rate if sample_rate > 0 else 0
            )
            bit_depth = 16  # FFmpeg konvertiert zu 16-bit
        else:
            # Fallback: WAV nochmal parsen
            audio_io = io.BytesIO(audio_bytes)
            with wave.open(audio_io, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                duration_seconds = frames / sample_rate if sample_rate > 0 else 0
                bit_depth = sample_width * 8

    except Exception as e:
        return AudioValidationResult(
            is_valid=False,
            error_code="INVALID_WAV_FORMAT",
            error_message=f"Converted audio parsing failed: {str(e)}",
            details={"wav_error": str(e), "format_details": format_details},
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # 5. Audio-Spezifikationen prüfen
    spec_errors = []
    if duration_seconds < specs.MIN_DURATION_SECONDS:
        spec_errors.append(
            f"Duration too short: {duration_seconds:.2f}s (min: {specs.MIN_DURATION_SECONDS}s)"
        )
    if duration_seconds > specs.MAX_DURATION_SECONDS:
        spec_errors.append(
            f"Duration too long: {duration_seconds:.2f}s (max: {specs.MAX_DURATION_SECONDS}s)"
        )

    if spec_errors:
        return AudioValidationResult(
            is_valid=False,
            error_code="INVALID_AUDIO_SPECS",
            error_message="; ".join(spec_errors),
            details={
                "current_specs": {
                    "duration_seconds": duration_seconds,
                    "sample_rate": sample_rate,
                    "bit_depth": bit_depth,
                    "channels": channels,
                },
                "required_specs": {
                    "min_duration_seconds": specs.MIN_DURATION_SECONDS,
                    "max_duration_seconds": specs.MAX_DURATION_SECONDS,
                    "sample_rate": specs.REQUIRED_SAMPLE_RATE,
                    "bit_depth": specs.REQUIRED_BIT_DEPTH,
                    "channels": specs.REQUIRED_CHANNELS,
                },
                "format_details": format_details,
            },
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # 6. Erfolgreiche Validierung
    return AudioValidationResult(
        is_valid=True,
        duration_seconds=duration_seconds,
        file_size_bytes=len(audio_bytes),
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=channels,
        validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        spec_conversion_applied=format_details.get("conversion_attempted", False),
        processed_audio=audio_bytes,
        details={"format_details": format_details, "conversion_success": success},
    )
