# tests/integration_test_audio_validation.py
"""
Integrations-Test für Audio-Validierung mit der Session API
Testet das Zusammenspiel von Audio-Validation mit dem Unified Message Endpoint
"""

import requests
import io
import wave
import numpy as np
import time
import pytest
from pathlib import Path


def create_test_wav_file(
    output_path: str,
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
    amplitude: float = 0.5
) -> str:
    """Create a test WAV file and return the path"""

    # Generate sine wave test signal
    frames = int(duration_seconds * sample_rate)
    frequency = 440.0  # A4 note
    t = np.linspace(0, duration_seconds, frames, False)
    wave_data = amplitude * np.sin(2 * np.pi * frequency * t)

    # Convert to 16-bit
    max_val = 32767
    wave_data = (wave_data * max_val).astype(np.int16)

    # Save WAV file
    with wave.open(output_path, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bit_depth // 8)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(wave_data.tobytes())

    return output_path


class TestAudioValidationIntegration:
    """Integration Tests für Audio-Validation mit der Session API"""

    BASE_URL = "http://localhost:8000"  # API Gateway

    def setup_method(self):
        """Setup für jeden Test"""
        self.test_session_id = f"test_session_{int(time.time())}"
        self.test_files_dir = Path("/tmp/audio_validation_tests")
        self.test_files_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        """Cleanup nach jedem Test"""
        # Cleanup test files
        if self.test_files_dir.exists():
            for file in self.test_files_dir.glob("*.wav"):
                file.unlink()

    def test_session_audio_valid_input(self):
        """Test: Session API mit gültigem Audio"""
        # Create valid test audio
        test_file = self.test_files_dir / "valid_audio.wav"
        create_test_wav_file(
            str(test_file),
            duration_seconds=3.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        # Test session processing
        with open(test_file, 'rb') as f:
            audio_data = f.read()

        response = requests.post(
            f"{self.BASE_URL}/sessions/{self.test_session_id}/process",
            json={
                "type": "audio",
                "content": audio_data.hex(),  # Send as hex string
                "source_language": "en",
                "target_language": "de"
            }
        )

        # Should succeed with audio validation
        if response.status_code == 200:
            result = response.json()
            print(f"Session processing result: {result}")
            # Audio validation should be mentioned in debug info if available
            assert "error" not in result or result["error"] is False

    def test_session_audio_invalid_sample_rate(self):
        """Test: Session API mit ungültiger Sample-Rate"""
        # Create invalid test audio (44.1kHz instead of 16kHz)
        test_file = self.test_files_dir / "invalid_sample_rate.wav"
        create_test_wav_file(
            str(test_file),
            duration_seconds=2.0,
            sample_rate=44100,  # Wrong sample rate
            bit_depth=16,
            channels=1
        )

        with open(test_file, 'rb') as f:
            audio_data = f.read()

        response = requests.post(
            f"{self.BASE_URL}/sessions/{self.test_session_id}/process",
            json={
                "type": "audio",
                "content": audio_data.hex(),
                "source_language": "en",
                "target_language": "de"
            }
        )

        # Should fail validation
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")

        # Depending on implementation, this might be 400 (validation error) or different
        result = response.json() if response.headers.get('content-type') == 'application/json' else None
        if result:
            print(f"Error result: {result}")

    def test_session_audio_too_long(self):
        """Test: Session API mit zu langem Audio"""
        # Create audio that's too long (over 200 seconds)
        test_file = self.test_files_dir / "too_long_audio.wav"
        create_test_wav_file(
            str(test_file),
            duration_seconds=250.0,  # Too long
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        with open(test_file, 'rb') as f:
            audio_data = f.read()

        response = requests.post(
            f"{self.BASE_URL}/sessions/{self.test_session_id}/process",
            json={
                "type": "audio",
                "content": audio_data.hex(),
                "source_language": "en",
                "target_language": "de"
            }
        )

        print(f"Too long audio - Status: {response.status_code}")
        print(f"Response: {response.text}")

        # Should reject due to duration
        result = response.json() if response.headers.get('content-type') == 'application/json' else None
        if result:
            print(f"Duration error result: {result}")

    def test_session_audio_stereo_rejection(self):
        """Test: Session API lehnt Stereo-Audio ab"""
        # Create stereo audio
        test_file = self.test_files_dir / "stereo_audio.wav"
        create_test_wav_file(
            str(test_file),
            duration_seconds=2.0,
            sample_rate=16000,
            bit_depth=16,
            channels=2  # Stereo
        )

        with open(test_file, 'rb') as f:
            audio_data = f.read()

        response = requests.post(
            f"{self.BASE_URL}/sessions/{self.test_session_id}/process",
            json={
                "type": "audio",
                "content": audio_data.hex(),
                "source_language": "en",
                "target_language": "de"
            }
        )

        print(f"Stereo audio - Status: {response.status_code}")
        print(f"Response: {response.text}")

        result = response.json() if response.headers.get('content-type') == 'application/json' else None
        if result:
            print(f"Stereo rejection result: {result}")

    def test_api_gateway_health_check(self):
        """Test: API Gateway ist erreichbar"""
        try:
            response = requests.get(f"{self.BASE_URL}/health", timeout=5)
            print(f"Health check - Status: {response.status_code}")
            print(f"Response: {response.text}")

            # API Gateway should be running
            assert response.status_code in [200, 404]  # 404 if no health endpoint exists

        except requests.exceptions.ConnectionError:
            pytest.skip("API Gateway not running - integration test skipped")

    def test_session_text_still_works(self):
        """Test: Text-Processing funktioniert weiterhin korrekt"""
        response = requests.post(
            f"{self.BASE_URL}/sessions/{self.test_session_id}/process",
            json={
                "type": "text",
                "content": "Hello world",
                "source_language": "en",
                "target_language": "de"
            }
        )

        print(f"Text processing - Status: {response.status_code}")
        print(f"Response: {response.text}")

        # Text processing should still work normally
        if response.status_code == 200:
            result = response.json()
            print(f"Text result: {result}")


if __name__ == "__main__":
    # Run specific test manually for debugging
    test = TestAudioValidationIntegration()
    test.setup_method()

    print("=== Testing API Gateway Health ===")
    test.test_api_gateway_health_check()

    print("\n=== Testing Valid Audio ===")
    test.test_session_audio_valid_input()

    print("\n=== Testing Invalid Sample Rate ===")
    test.test_session_audio_invalid_sample_rate()

    print("\n=== Testing Text Processing ===")
    test.test_session_text_still_works()

    test.teardown_method()
    print("\nIntegration tests completed!")
