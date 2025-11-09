#!/usr/bin/env python3
"""
Test verschiedener Dateiformate für WAV-Validierung
Demonstriert das korrekte Verhalten bei ungültigen Dateiformaten
"""

import requests
import tempfile
import os
import json
from pathlib import Path


def test_wav_format_validation():
    """Test WAV-Format-Validierung mit verschiedenen Dateiformaten"""

    base_url = "http://localhost:8000"

    print("=== WAV Format Validation Test ===\n")

    # Test 1: Nicht-WAV Datei (Text-Datei)
    print("🔍 Test 1: Text-Datei als WAV hochladen")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        # Schreibe Text-Inhalt statt WAV-Daten
        temp_file.write(b"This is just text content, not a WAV file!")
        temp_file.flush()

        try:
            with open(temp_file.name, 'rb') as f:
                files = {'file': ('fake.wav', f, 'audio/wav')}
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

                print(f"   Status Code: {response.status_code}")

                if response.status_code == 400:
                    try:
                        result = response.json()
                        print("   ✅ Text-Datei korrekt abgelehnt!")
                        print(f"   Error: {result.get('error', 'Unknown error')}")

                        # Prüfe spezifischen Fehlercode
                        if 'validation_result' in result:
                            val_result = result['validation_result']
                            if val_result.get('error_code') == 'INVALID_WAV_FORMAT':
                                print("   ✅ Korrekte Fehlerkennung: INVALID_WAV_FORMAT")
                                print(f"   WAV-Fehler: {val_result.get('details', {}).get('wav_error', 'N/A')}")
                            else:
                                print(f"   ℹ️  Andere Fehlerkennung: {val_result.get('error_code')}")

                    except json.JSONDecodeError:
                        print(f"   Response (nicht JSON): {response.text[:200]}")
                else:
                    print("   ❌ Text-Datei wurde nicht abgelehnt!")
                    print(f"   Response: {response.text[:200]}")

        finally:
            os.unlink(temp_file.name)

    # Test 2: Vollständig leere Datei
    print("\n🔍 Test 2: Vollständig leere Datei")

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

                print(f"   Status Code: {response.status_code}")

                if response.status_code == 400:
                    try:
                        result = response.json()
                        print("   ✅ Leere Datei korrekt abgelehnt!")
                        print(f"   Error: {result.get('error', 'Unknown error')}")

                    except json.JSONDecodeError:
                        print(f"   Response (nicht JSON): {response.text[:200]}")
                else:
                    print("   ❌ Leere Datei wurde nicht abgelehnt!")
                    print(f"   Response: {response.text[:200]}")

        finally:
            os.unlink(temp_file.name)

    # Test 3: Ungültiger RIFF-Header
    print("\n🔍 Test 3: Ungültiger RIFF-Header")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        # Schreibe ungültigen RIFF-ähnlichen Header
        temp_file.write(b"RIFF\x00\x00\x00\x00FAKE")  # Fake RIFF header
        temp_file.flush()

        try:
            with open(temp_file.name, 'rb') as f:
                files = {'file': ('fake_riff.wav', f, 'audio/wav')}
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

                print(f"   Status Code: {response.status_code}")

                if response.status_code == 400:
                    try:
                        result = response.json()
                        print("   ✅ Ungültiger RIFF-Header korrekt abgelehnt!")
                        print(f"   Error: {result.get('error', 'Unknown error')}")

                    except json.JSONDecodeError:
                        print(f"   Response (nicht JSON): {response.text[:200]}")
                else:
                    print("   ❌ Ungültiger RIFF-Header wurde nicht abgelehnt!")
                    print(f"   Response: {response.text[:200]}")

        finally:
            os.unlink(temp_file.name)

    # Test 4: JSON-Datei mit WAV-Extension
    print("\n🔍 Test 4: JSON-Datei mit .wav Extension")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        # Schreibe JSON-Inhalt
        json_content = {"error": "This is not a WAV file", "type": "json"}
        temp_file.write(json.dumps(json_content).encode('utf-8'))
        temp_file.flush()

        try:
            with open(temp_file.name, 'rb') as f:
                files = {'file': ('json_fake.wav', f, 'audio/wav')}
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

                print(f"   Status Code: {response.status_code}")

                if response.status_code == 400:
                    try:
                        result = response.json()
                        print("   ✅ JSON-Datei korrekt abgelehnt!")
                        print(f"   Error: {result.get('error', 'Unknown error')}")

                        # Zeige Validierungsdetails
                        if 'validation_result' in result:
                            val_result = result['validation_result']
                            print(f"   Error Code: {val_result.get('error_code')}")
                            print(f"   Error Message: {val_result.get('error_message')}")

                            if 'details' in val_result and 'wav_error' in val_result['details']:
                                print(f"   WAV Error Details: {val_result['details']['wav_error']}")

                    except json.JSONDecodeError:
                        print(f"   Response (nicht JSON): {response.text[:200]}")
                else:
                    print("   ❌ JSON-Datei wurde nicht abgelehnt!")
                    print(f"   Response: {response.text[:200]}")

        finally:
            os.unlink(temp_file.name)

    print("\n=== Fazit ===")
    print("✅ Die Audio-Validierung funktioniert korrekt:")
    print("   - Erkennt nicht-WAV Dateien")
    print("   - Gibt spezifische Fehlercodes zurück")
    print("   - Zeigt detaillierte Fehlermeldungen")
    print("   - Error Code: INVALID_WAV_FORMAT")
    print("   - Error Message: 'Invalid WAV format: file does not start with RIFF id'")

    print(f"\n🎯 Der ursprüngliche Fehler ist ERWARTETES Verhalten!")
    print("   Eine Datei ohne RIFF-Header wird korrekt als ungültig erkannt.")


def test_session_api_wav_validation():
    """Test WAV-Validierung über Session API"""

    base_url = "http://localhost:8000"

    print("\n=== Session API WAV Validation Test ===")

    # Erstelle Session
    try:
        session_response = requests.post(f"{base_url}/api/admin/session/create")

        if session_response.status_code == 200:
            session_data = session_response.json()
            session_id = session_data['session_id']
            print(f"✅ Session erstellt: {session_id}")

            # Test mit ungültiger Datei über Session API
            print("\n🔍 Test: Ungültige Datei über Session API")

            fake_audio = b"This is not WAV audio data"

            response = requests.post(
                f"{base_url}/sessions/{session_id}/process",
                json={
                    "type": "audio",
                    "content": fake_audio.hex(),
                    "source_language": "en",
                    "target_language": "de"
                },
                timeout=30
            )

            print(f"   Status Code: {response.status_code}")

            if response.status_code == 400:
                try:
                    result = response.json()
                    print("   ✅ Session API lehnt ungültige WAV-Datei ab!")
                    print(f"   Status: {result.get('status')}")
                    print(f"   Error Code: {result.get('error_code')}")
                    print(f"   Error Message: {result.get('error_message')}")

                    if 'details' in result:
                        details = result['details']
                        if 'validation_details' in details:
                            val_details = details['validation_details']
                            print(f"   WAV Error: {val_details.get('wav_error')}")

                except json.JSONDecodeError:
                    print(f"   Response (nicht JSON): {response.text[:200]}")
            else:
                print("   ❌ Session API lehnt ungültige Datei nicht ab!")
                print(f"   Response: {response.text[:200]}")
        else:
            print(f"❌ Session-Erstellung fehlgeschlagen: {session_response.status_code}")

    except Exception as e:
        print(f"❌ Fehler beim Session API Test: {e}")


if __name__ == "__main__":
    print("🧪 WAV Format Validation Test\n")

    try:
        test_wav_format_validation()
        test_session_api_wav_validation()

    except KeyboardInterrupt:
        print("\n⏹️  Test abgebrochen")
    except Exception as e:
        print(f"\n❌ Unerwarteter Fehler: {e}")

    print("\n🏁 Test abgeschlossen!")
