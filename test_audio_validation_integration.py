#!/usr/bin/env python3
"""
Einfacher Test der Audio-Validierung mit der Session API
"""

import requests
import io
import wave
import numpy as np


def create_test_wav_bytes(
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
    amplitude: float = 0.5
) -> bytes:
    """Create test WAV audio as bytes"""

    # Generate sine wave test signal
    frames = int(duration_seconds * sample_rate)
    frequency = 440.0  # A4 note
    t = np.linspace(0, duration_seconds, frames, False)
    wave_data = amplitude * np.sin(2 * np.pi * frequency * t)

    # Convert to 16-bit
    max_val = 32767
    wave_data = (wave_data * max_val).astype(np.int16)

    # Create WAV file in memory
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bit_depth // 8)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(wave_data.tobytes())

    return wav_io.getvalue()


def test_session_endpoint():
    """Test the Session API with audio validation"""

    base_url = "http://localhost:8000"
    session_id = "test_audio_validation_session"

    print("=== Test 1: Valid Audio (16kHz, 16-bit, Mono) ===")
    valid_audio = create_test_wav_bytes(
        duration_seconds=3.0,
        sample_rate=16000,
        bit_depth=16,
        channels=1
    )

    try:
        response = requests.post(
            f"{base_url}/sessions/{session_id}/process",
            json={
                "type": "audio",
                "content": valid_audio.hex(),
                "source_language": "en",
                "target_language": "de"
            },
            timeout=30
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")

        if response.status_code == 200:
            result = response.json()
            print("✅ Valid audio accepted!")
            if "debug" in result:
                print(f"Debug info available: {len(result.get('debug', {}).get('steps', []))} steps")
        else:
            print("❌ Valid audio was rejected")

    except Exception as e:
        print(f"❌ Error with valid audio: {e}")

    print("\n=== Test 2: Invalid Audio (44.1kHz - wrong sample rate) ===")
    invalid_audio = create_test_wav_bytes(
        duration_seconds=2.0,
        sample_rate=44100,  # Wrong sample rate
        bit_depth=16,
        channels=1
    )

    try:
        response = requests.post(
            f"{base_url}/sessions/{session_id}/process",
            json={
                "type": "audio",
                "content": invalid_audio.hex(),
                "source_language": "en",
                "target_language": "de"
            },
            timeout=30
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")

        if response.status_code != 200:
            print("✅ Invalid audio correctly rejected!")
        else:
            result = response.json()
            if result.get("error"):
                print("✅ Invalid audio flagged as error!")
            else:
                print("❌ Invalid audio was unexpectedly accepted")

    except Exception as e:
        print(f"❌ Error with invalid audio: {e}")

    print("\n=== Test 3: Text Processing (should still work) ===")
    try:
        response = requests.post(
            f"{base_url}/sessions/{session_id}/process",
            json={
                "type": "text",
                "content": "Hello world",
                "source_language": "en",
                "target_language": "de"
            },
            timeout=30
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:300]}")

        if response.status_code == 200:
            print("✅ Text processing still working!")
        else:
            print("❌ Text processing broken")

    except Exception as e:
        print(f"❌ Error with text processing: {e}")

    print("\n=== Test 4: Stereo Audio (should be rejected) ===")
    stereo_audio = create_test_wav_bytes(
        duration_seconds=2.0,
        sample_rate=16000,
        bit_depth=16,
        channels=2  # Stereo - should be rejected
    )

    try:
        response = requests.post(
            f"{base_url}/sessions/{session_id}/process",
            json={
                "type": "audio",
                "content": stereo_audio.hex(),
                "source_language": "en",
                "target_language": "de"
            },
            timeout=30
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")

        if response.status_code != 200:
            print("✅ Stereo audio correctly rejected!")
        else:
            result = response.json()
            if result.get("error"):
                print("✅ Stereo audio flagged as error!")
            else:
                print("❌ Stereo audio was unexpectedly accepted")

    except Exception as e:
        print(f"❌ Error with stereo audio: {e}")


if __name__ == "__main__":
    print("Testing Audio Validation Integration\n")
    test_session_endpoint()
    print("\nTesting completed!")
