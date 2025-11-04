#!/usr/bin/env python3
"""
Test der Audio-Validierung mit dem bestehenden Pipeline-Endpoint
"""

import requests
import io
import wave
import numpy as np
import tempfile
import os


def create_test_wav_file(
    output_path: str,
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
    amplitude: float = 0.5
) -> str:
    """Create test WAV file and return the path"""

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


def test_pipeline_endpoint():
    """Test the /pipeline endpoint with audio validation"""

    base_url = "http://localhost:8000"

    print("=== Test 1: Valid Audio (16kHz, 16-bit, Mono) via Pipeline ===")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        valid_file = create_test_wav_file(
            temp_file.name,
            duration_seconds=3.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        try:
            with open(valid_file, 'rb') as f:
                files = {'file': ('test_valid.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=60
                )

                print(f"Status Code: {response.status_code}")
                if response.status_code == 200:
                    try:
                        result = response.json()
                        print("✅ Valid audio processed successfully!")

                        # Check if validation was performed
                        if "debug" in result and "steps" in result["debug"]:
                            steps = result["debug"]["steps"]
                            validation_steps = [s for s in steps if "validation" in s.get("step", "").lower()]
                            if validation_steps:
                                print(f"   Found validation steps: {len(validation_steps)}")
                                for step in validation_steps:
                                    print(f"   - {step.get('step')}: {step.get('output')}")
                            else:
                                print("   No validation steps found in debug info")

                        if result.get("error"):
                            print(f"   ⚠️ Error reported: {result.get('error_msg')}")
                        else:
                            print(f"   ✅ No errors reported")

                    except Exception as e:
                        print(f"   Response content (not JSON): {response.text[:500]}")
                else:
                    print(f"❌ Request failed: {response.text[:500]}")

        finally:
            os.unlink(valid_file)

    print("\n=== Test 2: Invalid Audio (44.1kHz - wrong sample rate) ===")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        invalid_file = create_test_wav_file(
            temp_file.name,
            duration_seconds=2.0,
            sample_rate=44100,  # Wrong sample rate
            bit_depth=16,
            channels=1
        )

        try:
            with open(invalid_file, 'rb') as f:
                files = {'file': ('test_invalid.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=60
                )

                print(f"Status Code: {response.status_code}")
                if response.status_code == 200:
                    try:
                        result = response.json()

                        if result.get("error"):
                            print("✅ Invalid audio correctly rejected!")
                            print(f"   Error: {result.get('error_msg')}")

                            # Check validation details
                            if "validation_result" in result:
                                val_result = result["validation_result"]
                                print(f"   Validation error code: {val_result.get('error_code')}")
                                print(f"   Validation error message: {val_result.get('error_message')}")
                        else:
                            print("❌ Invalid audio was unexpectedly accepted")
                            print(f"   Result: {result}")

                    except Exception as e:
                        print(f"   Response content (not JSON): {response.text[:500]}")
                else:
                    print(f"   Request failed with status {response.status_code}: {response.text[:500]}")

        finally:
            os.unlink(invalid_file)

    print("\n=== Test 3: Stereo Audio (should be rejected) ===")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        stereo_file = create_test_wav_file(
            temp_file.name,
            duration_seconds=2.0,
            sample_rate=16000,
            bit_depth=16,
            channels=2  # Stereo - should be rejected
        )

        try:
            with open(stereo_file, 'rb') as f:
                files = {'file': ('test_stereo.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=60
                )

                print(f"Status Code: {response.status_code}")
                if response.status_code == 200:
                    try:
                        result = response.json()

                        if result.get("error"):
                            print("✅ Stereo audio correctly rejected!")
                            print(f"   Error: {result.get('error_msg')}")

                            # Check validation details
                            if "validation_result" in result:
                                val_result = result["validation_result"]
                                print(f"   Validation error code: {val_result.get('error_code')}")
                        else:
                            print("❌ Stereo audio was unexpectedly accepted")

                    except Exception as e:
                        print(f"   Response content (not JSON): {response.text[:500]}")
                else:
                    print(f"   Request failed: {response.text[:500]}")

        finally:
            os.unlink(stereo_file)

    print("\n=== Test 4: Duration Too Long (should be rejected) ===")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        long_file = create_test_wav_file(
            temp_file.name,
            duration_seconds=250.0,  # Too long (over backend 200s limit)
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

        try:
            with open(long_file, 'rb') as f:
                files = {'file': ('test_long.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=60
                )

                print(f"Status Code: {response.status_code}")
                if response.status_code == 200:
                    try:
                        result = response.json()

                        if result.get("error"):
                            print("✅ Long audio correctly rejected!")
                            print(f"   Error: {result.get('error_msg')}")
                        else:
                            print("❌ Long audio was unexpectedly accepted")

                    except Exception as e:
                        print(f"   Response content (not JSON): {response.text[:500]}")
                else:
                    print(f"   Request failed: {response.text[:500]}")

        finally:
            os.unlink(long_file)


if __name__ == "__main__":
    print("Testing Audio Validation with Pipeline Endpoint\n")
    test_pipeline_endpoint()
    print("\nTesting completed!")
