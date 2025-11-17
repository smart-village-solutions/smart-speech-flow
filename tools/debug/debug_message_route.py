#!/usr/bin/env python3
"""
Debug Script für die /api/session/{session_id}/message Route
"""

import requests
import asyncio
import json

BASE_URL = "http://localhost:8000"

async def test_message_route():
    """Test die Message Route direkt"""

    # 1. Session erstellen
    print("1. Erstelle neue Session...")
    session_response = requests.post(f"{BASE_URL}/api/admin/session/create")
    if session_response.status_code not in [200, 201]:
        print(f"Fehler beim Erstellen der Session: {session_response.status_code}")
        print(session_response.text)
        return

    session_data = session_response.json()
    session_id = session_data["session_id"]
    print(f"   Session erstellt: {session_id}")

    # 2. Sprache auswählen (Customer Session aktivieren)
    print("2. Wähle Sprache...")
    language_response = requests.post(
        f"{BASE_URL}/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"}
    )
    if language_response.status_code != 200:
        print(f"Fehler bei der Sprachauswahl: {language_response.status_code}")
        print(language_response.text)
        return
    print("   Sprache gewählt: en")

    # 3. Audio senden - DETAILLIERT DEBUGGEN
    print("3. Sende Audio-Nachricht...")

    # Lade Audio-Datei
    try:
        with open("/root/projects/ssf-backend/examples/German.wav", "rb") as f:
            audio_data = f.read()
        print(f"   Audio-Datei geladen: {len(audio_data)} bytes")
    except Exception as e:
        print(f"   Fehler beim Laden der Audio-Datei: {e}")
        return

    # Sende Request mit detailliertem Error Handling
    try:
        files = {"file": ("German.wav", audio_data, "audio/wav")}
        data = {
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }

        print(f"   Request Data: {data}")
        print(f"   Audio Size: {len(audio_data)} bytes")

        response = requests.post(
            f"{BASE_URL}/api/session/{session_id}/message",
            files=files,
            data=data,
            timeout=60
        )

        print(f"   Response Status: {response.status_code}")
        print(f"   Response Headers: {dict(response.headers)}")

        if response.status_code == 200:
            result = response.json()
            print(f"   SUCCESS: Message ID {result['message_id']}")
        else:
            print(f"   ERROR Response: {response.text}")

            # Versuche JSON zu parsen falls möglich
            try:
                error_data = response.json()
                print(f"   ERROR JSON: {json.dumps(error_data, indent=2)}")
            except:
                pass

    except Exception as e:
        print(f"   Request Exception: {e}")
        import traceback
        traceback.print_exc()

    # 4. KURZ WARTEN damit Session sich stabilisiert
    import time
    print("4. Warte kurz...")
    time.sleep(2)

    # 5. ZWEITE NACHRICHT SENDEN (hier kommt wahrscheinlich der 500-Fehler)
    print("5. Sende ZWEITE Audio-Nachricht (Customer)...")

    try:
        with open("/root/projects/ssf-backend/examples/English.wav", "rb") as f:
            audio_data2 = f.read()
        print(f"   Audio-Datei geladen: {len(audio_data2)} bytes")
    except Exception as e:
        print(f"   Fehler beim Laden der zweiten Audio-Datei: {e}")
        return

    try:
        files2 = {"file": ("English.wav", audio_data2, "audio/wav")}
        data2 = {
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "customer"  # CUSTOMER statt ADMIN
        }

        print(f"   Request Data: {data2}")
        print(f"   Audio Size: {len(audio_data2)} bytes")

        response2 = requests.post(
            f"{BASE_URL}/api/session/{session_id}/message",
            files=files2,
            data=data2,
            timeout=60
        )

        print(f"   Response Status: {response2.status_code}")
        print(f"   Response Headers: {dict(response2.headers)}")

        if response2.status_code == 200:
            result2 = response2.json()
            print(f"   SUCCESS: Message ID {result2['message_id']}")
        else:
            print(f"   ERROR Response: {response2.text}")

            # Versuche JSON zu parsen falls möglich
            try:
                error_data2 = response2.json()
                print(f"   ERROR JSON: {json.dumps(error_data2, indent=2)}")
            except:
                pass

    except Exception as e:
        print(f"   Request Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_message_route())
