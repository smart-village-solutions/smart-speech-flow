#!/usr/bin/env python3
"""
Debug Script für WebSocket + Message Route Interaktion
"""

import requests
import asyncio
import json
import websockets
import time

BASE_URL = "http://localhost:8000"
WS_BASE_URL = "ws://localhost:8000"

async def test_with_websockets():
    """Test die Message Route mit aktiven WebSocket-Verbindungen"""

    # 1. Session erstellen
    print("1. Erstelle neue Session...")
    session_response = requests.post(f"{BASE_URL}/api/admin/session/create")
    if session_response.status_code not in [200, 201]:
        print(f"Fehler beim Erstellen der Session: {session_response.status_code}")
        return

    session_data = session_response.json()
    session_id = session_data["session_id"]
    print(f"   Session erstellt: {session_id}")

    # 2. Sprache auswählen
    print("2. Wähle Sprache...")
    language_response = requests.post(
        f"{BASE_URL}/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": "en"}
    )
    if language_response.status_code != 200:
        print(f"Fehler bei der Sprachauswahl: {language_response.status_code}")
        return
    print("   Sprache gewählt: en")

    # 3. WebSocket-Verbindungen öffnen
    print("3. Öffne WebSocket-Verbindungen...")
    try:
        admin_ws = await websockets.connect(f"{WS_BASE_URL}/ws/{session_id}/admin")
        print("   Admin WebSocket verbunden")

        customer_ws = await websockets.connect(f"{WS_BASE_URL}/ws/{session_id}/customer")
        print("   Customer WebSocket verbunden")

        # Kurz warten damit Verbindungen sich stabilisieren
        await asyncio.sleep(1)

    except Exception as e:
        print(f"   WebSocket-Fehler: {e}")
        return

    try:
        # 4. Erste Nachricht (Admin -> Customer)
        print("4. Sende erste Audio-Nachricht (Admin)...")

        with open("/root/projects/ssf-backend/examples/German.wav", "rb") as f:
            audio_data1 = f.read()

        files1 = {"file": ("German.wav", audio_data1, "audio/wav")}
        data1 = {
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }

        print(f"   Sende Audio-Request...")
        response1 = requests.post(
            f"{BASE_URL}/api/session/{session_id}/message",
            files=files1,
            data=data1,
            timeout=30
        )

        print(f"   Response Status: {response1.status_code}")
        if response1.status_code == 200:
            print("   ✅ Erste Nachricht erfolgreich")
        else:
            print(f"   ❌ Erste Nachricht fehlgeschlagen: {response1.text}")
            return

        # 5. Kurz warten
        await asyncio.sleep(2)

        # 6. Zweite Nachricht (Customer -> Admin) - HIER KOMMT DER 500 FEHLER
        print("5. Sende zweite Audio-Nachricht (Customer)...")

        with open("/root/projects/ssf-backend/examples/English.wav", "rb") as f:
            audio_data2 = f.read()

        files2 = {"file": ("English.wav", audio_data2, "audio/wav")}
        data2 = {
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "customer"
        }

        print(f"   Sende Audio-Request...")
        try:
            response2 = requests.post(
                f"{BASE_URL}/api/session/{session_id}/message",
                files=files2,
                data=data2,
                timeout=30
            )

            print(f"   Response Status: {response2.status_code}")
            if response2.status_code == 200:
                print("   ✅ Zweite Nachricht erfolgreich")
            else:
                print(f"   ❌ Zweite Nachricht fehlgeschlagen: {response2.text}")
                try:
                    error_data = response2.json()
                    print(f"   Error JSON: {json.dumps(error_data, indent=2)}")
                except:
                    pass
        except requests.RequestException as e:
            print(f"   Request Exception: {e}")

    finally:
        # Cleanup
        try:
            await admin_ws.close()
            await customer_ws.close()
            print("   WebSocket-Verbindungen geschlossen")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(test_with_websockets())
