#!/usr/bin/env python3
"""
Test der Audio-Validierung mit ungültigen Audiodateien
"""

import requests
import tempfile
import os


def test_invalid_audio_formats():
    """Test mit ungültigen Audio-Formaten"""

    base_url = "http://localhost:8000"

    print("=== Test: Ungültige Datei (nicht WAV) ===")

    # Erstelle eine Fake-Audio-Datei (kein WAV)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        # Schreibe einfach Text in die Datei statt WAV-Daten
        temp_file.write(b"This is not a WAV file, just text content")
        temp_file.flush()

        try:
            with open(temp_file.name, 'rb') as f:
                files = {'file': ('invalid.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=30
                )

                print(f"Status Code: {response.status_code}")

                if response.status_code == 400:
                    result = response.json()
                    print("✅ Invalid audio correctly rejected!")
                    print(f"Error: {result.get('error', 'No error message')}")

                    # Schaue nach Audio-Validation-Fehler
                    if "validation" in result.get('error', '').lower():
                        print("✅ Audio validation error detected!")
                    elif "Audio validation failed" in result.get('error', ''):
                        print("✅ Audio validation rejection confirmed!")
                    else:
                        print("ℹ️  Audio rejected by different step in pipeline")

                else:
                    print(f"❌ Invalid audio was not rejected properly")
                    print(f"Response: {response.text[:300]}")

        finally:
            os.unlink(temp_file.name)

    print("\n=== Test: Leere Datei ===")

    # Erstelle eine leere Datei
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_file.flush()  # Datei bleibt leer

        try:
            with open(temp_file.name, 'rb') as f:
                files = {'file': ('empty.wav', f, 'audio/wav')}
                data = {
                    'source_lang': 'en',
                    'target_lang': 'de',
                    'debug': 'true'
                }

                response = requests.post(
                    f"{base_url}/pipeline",
                    files=files,
                    data=data,
                    timeout=30
                )

                print(f"Status Code: {response.status_code}")

                if response.status_code == 400:
                    result = response.json()
                    print("✅ Empty file correctly rejected!")
                    print(f"Error: {result.get('error', '')}")
                else:
                    print(f"❌ Empty file not rejected properly")
                    print(f"Response: {response.text[:300]}")

        finally:
            os.unlink(temp_file.name)


if __name__ == "__main__":
    print("Testing Audio Validation with Invalid Files\n")
    test_invalid_audio_formats()
    print("\nTesting completed!")
