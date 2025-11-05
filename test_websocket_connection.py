#!/usr/bin/env python3
import asyncio
import websockets
import json

async def test_websocket():
    """Test WebSocket connection to trigger metrics collection"""
    uri = "ws://localhost:8000/ws/2B73C3C3?client_type=customer"

    try:
        print(f"Verbinde mit {uri}...")
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket-Verbindung erfolgreich!")

            # Sende eine Test-Nachricht
            test_message = {
                "type": "text_message",
                "content": "Hello WebSocket Test",
                "timestamp": "2025-11-05T10:00:00Z"
            }

            await websocket.send(json.dumps(test_message))
            print("📤 Test-Nachricht gesendet")

            # Warte auf Antwort
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"📥 Antwort erhalten: {response}")
            except asyncio.TimeoutError:
                print("⏰ Timeout - keine Antwort erhalten")

            # Halte Verbindung kurz offen um Metriken zu generieren
            await asyncio.sleep(2)

        print("🔌 WebSocket-Verbindung geschlossen")

    except Exception as e:
        print(f"❌ Fehler: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())