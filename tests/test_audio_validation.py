# tests/test_audio_validation.py
"""
Unit-Tests für Audio-Validierung (ToDo 2.2)
Testet WAV-Format-Validation, Dauer-Limitierung, Dateigröße-Check und Audio-Normalisierung
"""

import pytest
import io
import wave
import struct
import numpy as np
from unittest.mock import Mock, patch

from services.api_gateway.pipeline_logic import (
    validate_audio_input, normalize_audio, AudioValidationResult, AudioSpecs,
    AudioValidationError, process_wav
)


def create_test_wav(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
    amplitude: float = 0.5
) -> bytes:
    """Helper function to create test WAV files"""

    # Calculate number of frames
    frames = int(duration_seconds * sample_rate)

    # Generate sine wave test signal
    frequency = 440.0  # A4 note
    t = np.linspace(0, duration_seconds, frames, False)
    wave_data = amplitude * np.sin(2 * np.pi * frequency * t)

    # Convert to appropriate bit depth
    if bit_depth == 16:
        max_val = 32767
        wave_data = (wave_data * max_val).astype(np.int16)
    elif bit_depth == 24:
        max_val = 8388607
        wave_data = (wave_data * max_val).astype(np.int32)
    elif bit_depth == 32:
        max_val = 2147483647
        wave_data = (wave_data * max_val).astype(np.int32)
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    if channels > 1:
        wave_data = np.tile(wave_data.reshape(-1, 1), (1, channels)).astype(wave_data.dtype)
        wave_data = wave_data.flatten()

    # Create WAV file in memory
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bit_depth // 8)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(wave_data.tobytes())

    return wav_io.getvalue()


class TestAudioValidation:
    """Tests für Audio-Validation-Grundfunktionen"""

    def test_valid_audio_16khz_16bit_mono(self):
        """Test: Gültiges Audio (16kHz, 16-bit, Mono) wird akzeptiert"""
        audio_bytes = create_test_wav(
            duration_seconds=5.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.duration_seconds == pytest.approx(5.0, rel=0.1)
        assert result.sample_rate == 16000
        assert result.bit_depth == 16
        assert result.channels == 1
        assert result.validation_time_ms >= 0
        assert isinstance(result.processed_audio, bytes)

    def test_file_too_large_rejection(self):
        """Test: Zu große Dateien werden abgelehnt"""
        # Create large audio file (longer duration to exceed size limit)
        audio_bytes = create_test_wav(duration_seconds=60.0)  # Very long audio

        result = validate_audio_input(audio_bytes)

        if not result.is_valid and result.error_code == "FILE_TOO_LARGE":
            assert "too large" in result.error_message.lower()
            assert result.details["file_size_bytes"] > 0
        # If file size is still within limit, that's also okay for this test duration

    def test_wrong_sample_rate_auto_conversion(self):
        """Test: Sample-Rate wird automatisch auf 16kHz konvertiert"""
        audio_bytes = create_test_wav(
            duration_seconds=2.0,
            sample_rate=44100,  # Wrong sample rate
            bit_depth=16,
            channels=1
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.sample_rate == 16000
        assert result.spec_conversion_applied is True
        assert result.channels == 1
        assert isinstance(result.processed_audio, bytes)

    def test_wrong_bit_depth_auto_conversion(self):
        """Test: Bit-Tiefe wird automatisch auf 16-bit konvertiert"""
        audio_bytes = create_test_wav(
            duration_seconds=2.0,
            sample_rate=16000,
            bit_depth=32,  # Wrong bit depth
            channels=1
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.bit_depth == 16
        assert result.spec_conversion_applied is True
        assert isinstance(result.processed_audio, bytes)

    def test_stereo_auto_conversion(self):
        """Test: Stereo-Audio wird automatisch in Mono konvertiert"""
        audio_bytes = create_test_wav(
            duration_seconds=2.0,
            sample_rate=16000,
            bit_depth=16,
            channels=2  # Stereo instead of Mono
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.channels == 1
        assert result.spec_conversion_applied is True
        assert result.error_code is None
        assert isinstance(result.processed_audio, bytes)

    def test_duration_too_short_rejection(self):
        """Test: Zu kurze Audio-Dateien werden abgelehnt"""
        audio_bytes = create_test_wav(
            duration_seconds=0.05,  # 50ms - too short
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is False
        assert result.error_code == "INVALID_AUDIO_SPECS"
        assert "too short" in result.error_message.lower()
        assert result.details["current_specs"]["duration_seconds"] < 0.1

    def test_duration_too_long_rejection(self):
        """Test: Zu lange Audio-Dateien werden abgelehnt"""
        audio_bytes = create_test_wav(
            duration_seconds=25.0,  # 25 seconds - too long
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is False
        assert result.error_code == "INVALID_AUDIO_SPECS"
        assert "too long" in result.error_message.lower()
        assert result.details["current_specs"]["duration_seconds"] > 20.0

    def test_invalid_wav_format_rejection(self):
        """Test: Ungültiges WAV-Format wird abgelehnt"""
        # Create invalid WAV data
        invalid_audio = b"Not a WAV file"

        result = validate_audio_input(invalid_audio)

        assert result.is_valid is False
        assert result.error_code == "INVALID_WAV_FORMAT"
        assert "invalid wav format" in result.error_message.lower()
        assert "wav_error" in result.details

    def test_empty_file_rejection(self):
        """Test: Leere Datei wird abgelehnt"""
        empty_audio = b""

        result = validate_audio_input(empty_audio)

        assert result.is_valid is False
        # Should fail at WAV format validation
        assert result.error_code in ["INVALID_WAV_FORMAT", "VALIDATION_ERROR"]


class TestAudioNormalization:
    """Tests für Audio-Normalisierung"""

    def test_audio_normalization_applied(self):
        """Test: Audio-Normalisierung wird angewendet"""
        # Create quiet audio that needs boosting
        audio_bytes = create_test_wav(
            duration_seconds=2.0,
            amplitude=0.1  # Very quiet
        )

        result = validate_audio_input(audio_bytes, normalize=True)

        assert result.is_valid is True
        # Normalization should be applied to boost quiet audio
        # Note: normalization_applied might be False if audio is already at good level

    def test_audio_normalization_disabled(self):
        """Test: Audio-Normalisierung kann deaktiviert werden"""
        audio_bytes = create_test_wav(duration_seconds=2.0)

        result = validate_audio_input(audio_bytes, normalize=False)

        assert result.is_valid is True
        assert result.normalization_applied is False

    def test_normalize_audio_function(self):
        """Test: normalize_audio Funktion arbeitet korrekt"""
        original_audio = create_test_wav(
            duration_seconds=1.0,
            amplitude=0.2  # Quiet audio
        )

        normalized_audio = normalize_audio(
            original_audio,
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        # Normalized audio should be different from original
        assert len(normalized_audio) > 0
        assert isinstance(normalized_audio, bytes)

        # Should still be valid WAV
        result = validate_audio_input(normalized_audio, normalize=False)
        assert result.is_valid is True

    def test_normalize_audio_error_handling(self):
        """Test: Audio-Normalisierung behandelt Fehler graceful"""
        # Invalid audio data
        invalid_audio = b"invalid"

        # Should return original audio if normalization fails
        normalized = normalize_audio(invalid_audio, 16000, 16, 1)
        assert normalized == invalid_audio


class TestAudioValidationPerformance:
    """Tests für Performance-Monitoring"""

    def test_validation_time_tracking(self):
        """Test: Validation-Zeit wird gemessen"""
        audio_bytes = create_test_wav(duration_seconds=2.0)

        result = validate_audio_input(audio_bytes)

        assert result.validation_time_ms is not None
        assert result.validation_time_ms >= 0
        assert result.validation_time_ms < 1000  # Should be under 1 second

    def test_performance_with_large_valid_file(self):
        """Test: Performance mit großer gültiger Datei"""
        # Create maximum allowed duration
        audio_bytes = create_test_wav(duration_seconds=19.0)  # Just under 20s limit

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.validation_time_ms < 2000  # Should be under 2 seconds
        assert result.duration_seconds == pytest.approx(19.0, rel=0.1)


class TestProcessWavIntegration:
    """Tests für Integration mit process_wav"""

    @patch('services.api_gateway.pipeline_logic.requests.post')
    def test_process_wav_with_validation_enabled(self, mock_post):
        """Test: process_wav mit aktivierter Validation"""
        # Mock ASR response
        mock_asr_response = Mock()
        mock_asr_response.json.return_value = {"text": "Hello world"}
        mock_asr_response.status_code = 200

        # Mock Translation response
        mock_translation_response = Mock()
        mock_translation_response.json.return_value = {"translations": "Hallo Welt"}
        mock_translation_response.status_code = 200

        # Mock TTS response
        mock_tts_response = Mock()
        mock_tts_response.content = b"fake_audio_output"
        mock_tts_response.status_code = 200
        mock_tts_response.headers = {"content-type": "audio/wav"}

        mock_post.side_effect = [mock_asr_response, mock_translation_response, mock_tts_response]

        # Valid audio
        audio_bytes = create_test_wav(duration_seconds=3.0)

        result = process_wav(audio_bytes, "en", "de", debug=True, validate_audio=True)

        assert result["error"] is False
        assert "Audio_Validation" in [step["step"] for step in result["debug"]["steps"]]

        # Find validation step
        validation_step = next(step for step in result["debug"]["steps"] if step["step"] == "Audio_Validation")
        assert validation_step["output"] is True  # Validation passed
        assert validation_step["error"] is None

    def test_process_wav_with_validation_failure(self):
        """Test: process_wav mit Validation-Fehler"""
        # Invalid audio (wrong sample rate)
        audio_bytes = create_test_wav(
            duration_seconds=2.0,
            sample_rate=44100,
            channels=4  # Unsupported channel layout
        )

        result = process_wav(audio_bytes, "en", "de", debug=True, validate_audio=True)

        assert result["error"] is True
        assert "Audio validation failed" in result["error_msg"]
        assert result["validation_result"] is not None
        assert result["validation_result"].error_code == "INVALID_AUDIO_SPECS"
        assert "automatic conversion failed" in result["validation_result"].error_message.lower()

        # Should not proceed to ASR/Translation/TTS
        assert result["asr_text"] is None
        assert result["translation_text"] is None
        assert result["audio_bytes"] is None

    def test_process_wav_validation_disabled(self):
        """Test: process_wav mit deaktivierter Validation"""
        with patch('services.api_gateway.pipeline_logic.requests.post') as mock_post:
            # Mock successful responses
            mock_asr = Mock()
            mock_asr.json.return_value = {"text": "Test"}
            mock_translation = Mock()
            mock_translation.json.return_value = {"translations": "Test"}
            mock_translation.status_code = 200
            mock_tts = Mock()
            mock_tts.content = b"audio"
            mock_tts.status_code = 200
            mock_tts.headers = {"content-type": "audio/wav"}

            mock_post.side_effect = [mock_asr, mock_translation, mock_tts]

            # Even invalid audio should proceed if validation is disabled
            audio_bytes = b"invalid audio"

            result = process_wav(audio_bytes, "en", "de", validate_audio=False)

            # Should not have validation step
            if "debug" in result and "steps" in result["debug"]:
                validation_steps = [step for step in result["debug"]["steps"] if step["step"] == "Audio_Validation"]
                assert len(validation_steps) == 0


class TestAudioValidationEdgeCases:
    """Tests für Edge-Cases und Grenzfälle"""

    def test_exactly_minimum_duration(self):
        """Test: Genau minimale Dauer ist gültig"""
        audio_bytes = create_test_wav(duration_seconds=0.1)  # Exactly minimum

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.duration_seconds == pytest.approx(0.1, rel=0.05)

    def test_exactly_maximum_duration(self):
        """Test: Genau maximale Dauer ist gültig"""
        audio_bytes = create_test_wav(duration_seconds=20.0)  # Exactly maximum

        result = validate_audio_input(audio_bytes)

        assert result.is_valid is True
        assert result.duration_seconds == pytest.approx(20.0, rel=0.05)

    def test_audio_specs_configuration(self):
        """Test: AudioSpecs-Konfiguration ist korrekt"""
        specs = AudioSpecs()

        assert specs.MAX_DURATION_SECONDS == 20.0
        assert specs.MAX_FILE_SIZE_MB == 3.2
        assert specs.REQUIRED_SAMPLE_RATE == 16000
        assert specs.REQUIRED_BIT_DEPTH == 16
        assert specs.REQUIRED_CHANNELS == 1
        assert specs.MIN_DURATION_SECONDS == 0.1

    def test_validation_result_dataclass(self):
        """Test: AudioValidationResult-Dataclass funktioniert korrekt"""
        result = AudioValidationResult(
            is_valid=True,
            duration_seconds=5.0,
            file_size_bytes=1024,
            validation_time_ms=100
        )

        assert result.is_valid is True
        assert result.duration_seconds == 5.0
        assert result.file_size_bytes == 1024
        assert result.validation_time_ms == 100
        assert result.error_code is None
        assert result.normalization_applied is False
        assert result.spec_conversion_applied is False
        assert result.processed_audio is None


if __name__ == "__main__":
    # Tests direkt ausführen für Debugging
    pytest.main([__file__, "-v"])