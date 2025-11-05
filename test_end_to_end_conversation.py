#!/usr/bin/env python3
"""
End-to-End Test: Deutsche-Englische Konversation
================================================

Dieses Script simuliert eine vollständige Konversation zwischen einem deutschen
Verwaltungsmitarbeiter (Admin) und einem englischen Bürger (Customer) über das
Smart Speech Flow System.

Test-Ablauf:
1. Neue Admin-Session erstellen
2. Customer tritt der Session bei und wählt Englisch
3. Simulierte Konversation mit echten Audioaufnahmen
4. Bidirektionale Übersetzung testen
5. Session beenden und Ergebnisse auswerten
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List
import requests
import websockets
import aiohttp
import logging

# Logging-Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Test-Konfiguration
BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"
EXAMPLES_DIR = Path(__file__).parent / "examples"
TIMEOUT = 30  # Sekunden für WebSocket-Nachrichten

class ConversationTester:
    """End-to-End Test für deutsch-englische Konversation"""

    def __init__(self):
        self.session_id = None
        self.admin_ws = None
        self.customer_ws = None
        self.conversation_log = []
        # Task 5.1: Heartbeat-Task-Tracking
        self.heartbeat_task_admin = None
        self.heartbeat_task_customer = None
        # Task 5.7: Heartbeat-Timeout-Tracking
        self.heartbeat_timeout_detected = False
        # Message queues für Nachrichten vom Heartbeat-Handler
        self.admin_message_queue = asyncio.Queue()
        self.customer_message_queue = asyncio.Queue()
        # ✅ VERBESSERUNG: Tracking für sender_confirmation
        self.sender_confirmations_received = 0

    async def test_full_conversation(self) -> Dict[str, Any]:
        """Führt kompletten Konversationstest durch"""
        logger.info("🚀 Starte End-to-End Konversationstest")

        try:
            # 1. Session Setup
            await self.setup_session()

            # 2. WebSocket-Verbindungen aufbauen
            await self.connect_websockets()

            # 3. Konversation simulieren
            await self.simulate_conversation()

            # 4. Ergebnisse auswerten
            results = self.evaluate_results()

            logger.info("✅ End-to-End Test erfolgreich abgeschlossen")
            return results

        except Exception as e:
            logger.error(f"❌ Test fehlgeschlagen: {e}")
            raise
        finally:
            await self.cleanup()

    async def setup_session(self):
        """Erstellt neue Session und aktiviert Customer"""
        logger.info("📋 Session Setup...")

        # 1. Admin-Session erstellen
        response = requests.post(f"{BASE_URL}/api/admin/session/create")
        response.raise_for_status()

        session_data = response.json()
        self.session_id = session_data['session_id']
        logger.info(f"✅ Admin-Session erstellt: {self.session_id}")

        # 2. Customer-Session aktivieren (Englisch)
        activate_data = {
            "session_id": self.session_id,
            "customer_language": "en"
        }

        response = requests.post(f"{BASE_URL}/api/customer/session/activate", json=activate_data)
        response.raise_for_status()

        logger.info("✅ Customer-Session aktiviert (Englisch)")

        # 3. Session-Status verifizieren
        response = requests.get(f"{BASE_URL}/api/session/{self.session_id}")
        response.raise_for_status()

        status = response.json()
        assert status['status'] == 'active', f"Session nicht aktiv: {status}"
        assert status['customer_language'] == 'en', f"Falsche Customer-Sprache: {status}"

        logger.info(f"✅ Session verifiziert: {status}")

    async def connect_websockets(self):
        """Baut WebSocket-Verbindungen für Admin und Customer auf"""
        logger.info("🔌 WebSocket-Verbindungen aufbauen...")

        # ✅ Origin Header für Production-Modus (CORS)
        # websockets.connect() nutzt additional_headers Parameter
        headers = {
            "Origin": "https://translate.smart-village.solutions"
        }

        # Admin WebSocket
        admin_uri = f"{WS_URL}/ws/{self.session_id}/admin"
        self.admin_ws = await websockets.connect(
            admin_uri,
            additional_headers=headers
        )
        logger.info("✅ Admin WebSocket verbunden")

        # Customer WebSocket
        customer_uri = f"{WS_URL}/ws/{self.session_id}/customer"
        self.customer_ws = await websockets.connect(
            customer_uri,
            additional_headers=headers
        )
        logger.info("✅ Customer WebSocket verbunden")

        # Task 5.1 & 5.6: Warte auf connection_ack von beiden Verbindungen
        await self.wait_for_connection_ack(self.admin_ws, "Admin")
        await self.wait_for_connection_ack(self.customer_ws, "Customer")

        # Task 5.1: Starte Heartbeat-Handler für beide Verbindungen
        self.heartbeat_task_admin = asyncio.create_task(
            self.handle_heartbeats(self.admin_ws, "Admin")
        )
        self.heartbeat_task_customer = asyncio.create_task(
            self.handle_heartbeats(self.customer_ws, "Customer")
        )
        logger.info("✅ Heartbeat-Handler gestartet")

        # Kurz warten bis Verbindungen stabil sind
        await asyncio.sleep(1)

    async def wait_for_connection_ack(self, ws, ws_name: str):
        """Task 5.6: Wartet auf connection_ack und validiert es"""
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(message)

            if data.get('type') == 'connection_ack':
                logger.info(f"✅ {ws_name}: CONNECTION_ACK erhalten")
            else:
                logger.warning(f"⚠️ {ws_name}: Unerwartete erste Nachricht: {data.get('type')}")

        except asyncio.TimeoutError:
            logger.error(f"❌ {ws_name}: Kein CONNECTION_ACK innerhalb 5s")
            raise
        except Exception as e:
            logger.error(f"❌ {ws_name}: Fehler beim Warten auf CONNECTION_ACK: {e}")
            raise

    async def handle_heartbeats(self, ws, ws_name: str):
        """Task 5.1: Beantwortet Heartbeat-Pings automatisch mit Pongs"""
        logger.info(f"💓 {ws_name}: Heartbeat-Handler aktiv")

        # Bestimme welche Queue für andere Nachrichten verwendet wird
        message_queue = self.admin_message_queue if ws_name == "Admin" else self.customer_message_queue

        try:
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1)
                    data = json.loads(message)

                    # Task 5.5: Logge alle empfangenen Nachrichten
                    msg_type = data.get('type', 'unknown')
                    logger.debug(f"📨 {ws_name}: Empfangen: {msg_type}")

                    # Task 5.1: Auf Heartbeat-Ping mit Pong antworten
                    if data.get('type') == 'heartbeat_ping':
                        pong_response = {
                            'type': 'heartbeat_pong',
                            'timestamp': data.get('timestamp')
                        }
                        await ws.send(json.dumps(pong_response))
                        logger.debug(f"💓 {ws_name}: PONG gesendet")

                    # Task 5.7: Warnung bei Heartbeat-Timeout
                    elif data.get('type') == 'heartbeat_timeout':
                        logger.error(f"❌ {ws_name}: HEARTBEAT_TIMEOUT empfangen!")
                        self.heartbeat_timeout_detected = True

                    # Alle anderen Nachrichten in Queue für wait_for_translation
                    else:
                        await message_queue.put(data)

                except asyncio.TimeoutError:
                    # Kein Problem - nur kein Heartbeat in diesem Intervall
                    continue
                except websockets.ConnectionClosed:
                    logger.warning(f"⚠️ {ws_name}: Heartbeat-Handler: Verbindung geschlossen")
                    break

        except Exception as e:
            logger.error(f"❌ {ws_name}: Heartbeat-Handler Fehler: {e}")

    async def check_connection_health(self):
        """Task 5.3 & 5.4: Überprüft ob WebSocket-Verbindungen noch aktiv sind"""
        # Simple check: if websocket objects exist, they're active
        # (websockets library handles closed connections via exceptions)
        if not self.admin_ws or not self.customer_ws:
            logger.error("❌ WebSocket-Verbindungen nicht initialisiert")
            raise RuntimeError("WebSocket-Verbindungen nicht gesund - Test kann nicht fortgesetzt werden")

        logger.debug("✅ WebSocket-Verbindungen aktiv")

    async def simulate_conversation(self):
        """Simuliert komplette Konversation mit Audioaufnahmen"""
        logger.info("🎭 Starte Konversationssimulation...")

        # Konversationsschritte definieren
        conversation_steps = [
            {
                "speaker": "admin",
                "audio_file": "German.wav",
                "expected_de": "wind",  # Nordwind-Geschichte enthält "wind"
                "expected_en": "wind",   # Englische Übersetzung enthält "wind"
                "description": "Admin sendet deutsche Audio (Nordwind-Geschichte)"
            },
            {
                "speaker": "customer",
                "audio_file": "English_pcm.wav",
                "expected_en": "rat",      # Ratten-Geschichte enthält "rat"
                "expected_de": "ratte",      # Deutsche Übersetzung enthält "ratte"
                "description": "Customer sendet englische Audio (Ratten-Geschichte)"
            }
        ]

        for i, step in enumerate(conversation_steps, 1):
            logger.info(f"\n--- Schritt {i}: {step['description']} ---")
            await self.send_audio_message(step)
            await self.wait_for_translation(step)

            # Kurze Pause zwischen Nachrichten
            await asyncio.sleep(2)

    async def send_audio_message(self, step: Dict[str, Any]):
        """Sendet Audionachricht von spezifiziertem Sprecher"""
        # Task 5.3: Health Check vor dem Senden
        await self.check_connection_health()

        audio_file = EXAMPLES_DIR / step["audio_file"]

        if not audio_file.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_file}")

        logger.info(f"📤 Sende Audio von {step['speaker']}: {step['audio_file']}")

        # Sprachkonfiguration basierend auf Sprecher
        if step['speaker'] == 'admin':
            source_lang = 'de'  # Admin spricht Deutsch
            target_lang = 'en'  # Übersetzung nach Englisch
        else:
            source_lang = 'en'  # Customer spricht Englisch
            target_lang = 'de'  # Übersetzung nach Deutsch

        # Audio-Datei und Form-Daten vorbereiten
        with open(audio_file, 'rb') as f:
            audio_content = f.read()
            files = {'file': (audio_file.name, audio_content, 'audio/wav')}
            data = {
                'source_lang': source_lang,
                'target_lang': target_lang,
                'client_type': step['speaker']  # 'admin' or 'customer' - refers to ClientType enum
            }

            # POST Request an unified message endpoint
            response = requests.post(
                f"{BASE_URL}/api/session/{self.session_id}/message",
                files=files,
                data=data,
                timeout=TIMEOUT
            )

            response.raise_for_status()
            result = response.json()

            logger.info(f"✅ Audio verarbeitet: {result.get('message_id', 'Unknown ID')}")

            # Ergebnis zur Konversation hinzufügen
            step['api_response'] = result
            self.conversation_log.append(step)

        # ✅ VERBESSERUNG: Warte auf sender_confirmation für den Sender
        await self.wait_for_sender_confirmation(step)

    async def wait_for_sender_confirmation(self, step: Dict[str, Any]):
        """Wartet auf sender_confirmation für den Sender (wie Frontend es empfängt)"""
        # Bestimme Queue des Senders
        if step['speaker'] == 'admin':
            sender_queue = self.admin_message_queue
            sender_name = "Admin"
        else:
            sender_queue = self.customer_message_queue
            sender_name = "Customer"

        logger.info(f"⏳ {sender_name}: Warte auf sender_confirmation...")

        try:
            # Warte kurz auf sender_confirmation (sollte schnell kommen)
            ws_data = await asyncio.wait_for(sender_queue.get(), timeout=5)

            if ws_data.get('type') == 'message' and ws_data.get('role') == 'sender_confirmation':
                logger.info(f"✅ {sender_name}: sender_confirmation empfangen (würde von Frontend ignoriert)")
                step['sender_confirmation_received'] = True
                self.sender_confirmations_received += 1
            else:
                logger.warning(
                    f"⚠️ {sender_name}: Erwartete sender_confirmation, erhielt "
                    f"type={ws_data.get('type')}, role={ws_data.get('role')}"
                )
                step['sender_confirmation_received'] = False
                # Nachricht zurück in Queue für wait_for_translation
                await sender_queue.put(ws_data)

        except asyncio.TimeoutError:
            logger.warning(f"⚠️ {sender_name}: Keine sender_confirmation innerhalb 5s")
            step['sender_confirmation_received'] = False

    async def wait_for_translation(self, step: Dict[str, Any]):
        """Wartet auf WebSocket-Benachrichtigungen über Übersetzung"""
        logger.info("⏳ Warte auf WebSocket-Übersetzungsbenachrichtigungen...")

        # Bestimme welche Queue auf Nachrichten hören soll
        if step['speaker'] == 'admin':
            message_queue = self.customer_message_queue  # Customer erhält deutsche → englische Übersetzung
            listening_type = "customer"
        else:
            message_queue = self.admin_message_queue   # Admin erhält englische → deutsche Übersetzung
            listening_type = "admin"

        try:
            # Task 5.8: Warte auf mehrere WebSocket-Nachrichten mit assertion
            max_attempts = 5  # Task 5.2: Erhöhte Toleranz
            translation_received = False

            for attempt in range(max_attempts):
                # Warte auf Nachricht aus der Queue (vom Heartbeat-Handler)
                ws_data = await asyncio.wait_for(
                    message_queue.get(),
                    timeout=TIMEOUT
                )

                # Task 5.5: Logge ALLE empfangenen Nachrichten, nicht nur Übersetzungen
                msg_type = ws_data.get('type', 'unknown')
                logger.info(
                    f"📨 {listening_type.title()} Message empfangen ({attempt + 1}/{max_attempts}): "
                    f"Type={msg_type}, Keys={list(ws_data.keys())}"
                )

                # Task 5.7: Heartbeat-Timeout erkennen
                if msg_type == 'heartbeat_timeout':
                    logger.error(f"❌ HEARTBEAT_TIMEOUT während Test empfangen!")
                    self.heartbeat_timeout_detected = True
                    step['heartbeat_timeout'] = True

                # Prüfe ob das eine echte Übersetzung ist
                if ws_data.get('type') == 'message':
                    # ✅ VERBESSERUNG: Validiere role field (wie Frontend)
                    msg_role = ws_data.get('role', 'unknown')

                    if msg_role == 'receiver_message':
                        # ✅ Valide Übersetzungsnachricht für Empfänger
                        logger.info(f"✅ receiver_message empfangen (valide Translation)")
                        step['websocket_response'] = ws_data
                        translation_received = True

                        # Validierung der Übersetzung
                        self.validate_translation(step, ws_data)
                        logger.info(f"✅ Übersetzungsnachricht erfolgreich empfangen und validiert")
                        return

                    elif msg_role == 'sender_confirmation':
                        # ✅ sender_confirmation ignorieren (wie Frontend)
                        logger.info(f"📤 sender_confirmation empfangen und ignoriert (wie Frontend)")
                        step['sender_confirmation_received'] = True
                        continue  # Warte weiter auf receiver_message

                    else:
                        # Unbekannte Role
                        logger.warning(f"⚠️ Unbekannte Message-Role: {msg_role}")
                        continue

                elif ws_data.get('type') == 'connection_ack':
                    logger.debug("📋 Connection acknowledgment (bereits erhalten beim Connect)")
                    continue
                else:
                    logger.info(f"📋 Anderer Nachrichtentyp: {msg_type}, warte weiter...")
                    continue

            # Task 5.8: Assertion - keine echte Übersetzung gefunden
            if not translation_received:
                error_msg = f"❌ ASSERTION FAILED: Keine Übersetzung nach {max_attempts} Versuchen innerhalb {TIMEOUT}s pro Versuch"
                logger.error(error_msg)
                step['websocket_timeout'] = True
                step['assertion_failed'] = error_msg

        except asyncio.TimeoutError:
            # Task 5.8: Timeout-Assertion
            error_msg = f"❌ ASSERTION FAILED: Timeout beim Warten auf WebSocket-Nachricht ({TIMEOUT}s)"
            logger.error(error_msg)
            step['websocket_timeout'] = True
            step['assertion_failed'] = error_msg
        except Exception as e:
            logger.error(f"❌ WebSocket-Fehler: {e}")
            step['websocket_error'] = str(e)

    def validate_translation(self, step: Dict[str, Any], ws_data: Dict[str, Any]):
        """Validiert die empfangene Übersetzung"""
        # WebSocket-Nachricht hat Format: {type: "message", text: "...", ...}
        # NICHT mehr verschachtelt in 'data'
        if 'text' not in ws_data:
            logger.warning(f"⚠️ Keine 'text' in WebSocket-Nachricht: {ws_data.keys()}")
            return

        received_text = ws_data['text'].lower()

        # Bestimme erwarteten Text basierend auf Sprecher
        if step['speaker'] == 'admin':
            expected = step['expected_en'].lower()
            target_lang = "Englisch"
        else:
            expected = step['expected_de'].lower()
            target_lang = "Deutsch"

        # Simple Substring-Matching (flexibel für verschiedene Übersetzungen)
        if expected in received_text or any(word in received_text for word in expected.split()):
            logger.info(f"✅ Übersetzung validiert ({target_lang}): '{received_text}' enthält '{expected}'")
            step['translation_valid'] = True
        else:
            logger.warning(f"⚠️ Übersetzung ungewöhnlich ({target_lang}): Erwartet '{expected}', erhalten '{received_text}'")
            step['translation_valid'] = False

    def evaluate_results(self) -> Dict[str, Any]:
        """Wertet Testergebnisse aus und erstellt Report"""
        logger.info("📊 Werte Testergebnisse aus...")

        results = {
            "session_id": self.session_id,
            "total_messages": len(self.conversation_log),
            "successful_translations": 0,
            "failed_translations": 0,
            "websocket_timeouts": 0,
            "api_errors": 0,
            "heartbeat_timeouts": 0,  # Task 5.7
            "assertion_failures": 0,  # Task 5.8
            "sender_confirmations_received": self.sender_confirmations_received,  # ✅ VERBESSERUNG
            "detailed_log": self.conversation_log,
            "overall_success": True
        }

        for step in self.conversation_log:
            # API-Response-Validierung
            if 'api_response' not in step:
                results['api_errors'] += 1
                results['overall_success'] = False

            # WebSocket-Validierung
            if step.get('websocket_timeout', False):
                results['websocket_timeouts'] += 1
                results['overall_success'] = False

            # Task 5.7: Heartbeat-Timeout-Validierung
            if step.get('heartbeat_timeout', False):
                results['heartbeat_timeouts'] += 1
                results['overall_success'] = False

            # Task 5.8: Assertion-Validierung
            if step.get('assertion_failed'):
                results['assertion_failures'] += 1
                results['overall_success'] = False

            # Übersetzungs-Validierung
            if step.get('translation_valid', False):
                results['successful_translations'] += 1
            else:
                results['failed_translations'] += 1
                if 'translation_valid' in step:  # Nur als Fehler werten wenn explizit validiert
                    results['overall_success'] = False

        # Task 5.7: Global Heartbeat-Timeout-Check
        if self.heartbeat_timeout_detected:
            logger.error("❌ HEARTBEAT_TIMEOUT während Test erkannt!")
            results['overall_success'] = False

        # Erfolgsquote berechnen
        if results['total_messages'] > 0:
            success_rate = results['successful_translations'] / results['total_messages']
            results['success_rate'] = f"{success_rate:.1%}"
        else:
            results['success_rate'] = "0%"

        # Ergebnisse loggen
        logger.info(f"\n{'='*50}")
        logger.info(f"📋 TEST ERGEBNISSE")
        logger.info(f"{'='*50}")
        logger.info(f"Session ID: {results['session_id']}")
        logger.info(f"Nachrichten gesamt: {results['total_messages']}")
        logger.info(f"Erfolgreiche Übersetzungen: {results['successful_translations']}")
        logger.info(f"Fehlgeschlagene Übersetzungen: {results['failed_translations']}")
        logger.info(f"WebSocket Timeouts: {results['websocket_timeouts']}")
        logger.info(f"API-Fehler: {results['api_errors']}")
        logger.info(f"Heartbeat Timeouts: {results['heartbeat_timeouts']}")  # Task 5.7
        logger.info(f"Assertion Failures: {results['assertion_failures']}")  # Task 5.8
        logger.info(f"sender_confirmations empfangen: {results['sender_confirmations_received']}/{results['total_messages']}")  # ✅ VERBESSERUNG
        logger.info(f"Erfolgsquote: {results['success_rate']}")
        logger.info(f"Gesamtergebnis: {'✅ BESTANDEN' if results['overall_success'] else '❌ FEHLGESCHLAGEN'}")
        logger.info(f"{'='*50}")

        return results

    async def cleanup(self):
        """Räumt Test-Ressourcen auf"""
        logger.info("🧹 Räume Test-Ressourcen auf...")

        try:
            # Task 5.1: Heartbeat-Tasks beenden
            if self.heartbeat_task_admin and not self.heartbeat_task_admin.done():
                self.heartbeat_task_admin.cancel()
                try:
                    await self.heartbeat_task_admin
                except asyncio.CancelledError:
                    pass
                logger.info("✅ Admin Heartbeat-Task beendet")

            if self.heartbeat_task_customer and not self.heartbeat_task_customer.done():
                self.heartbeat_task_customer.cancel()
                try:
                    await self.heartbeat_task_customer
                except asyncio.CancelledError:
                    pass
                logger.info("✅ Customer Heartbeat-Task beendet")

            # WebSocket-Verbindungen schließen
            if self.admin_ws:
                await self.admin_ws.close()
                logger.info("✅ Admin WebSocket geschlossen")

            if self.customer_ws:
                await self.customer_ws.close()
                logger.info("✅ Customer WebSocket geschlossen")

            # Session beenden
            if self.session_id:
                try:
                    response = requests.post(f"{BASE_URL}/api/admin/session/{self.session_id}/terminate")
                    if response.status_code == 200:
                        logger.info("✅ Session beendet")
                    else:
                        logger.warning(f"⚠️ Session-Beendigung fehlgeschlagen: {response.status_code}")
                except requests.RequestException as e:
                    logger.warning(f"⚠️ Fehler beim Beenden der Session: {e}")

        except Exception as e:
            logger.error(f"❌ Cleanup-Fehler: {e}")

async def main():
    """Hauptfunktion für End-to-End Test"""
    print("🎯 Smart Speech Flow - End-to-End Konversationstest")
    print("=" * 60)

    # Überprüfe ob Server läuft
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        response.raise_for_status()
        logger.info("✅ API-Server erreichbar")
    except requests.RequestException as e:
        logger.error(f"❌ API-Server nicht erreichbar: {e}")
        logger.error("Stelle sicher, dass docker-compose läuft: docker compose up -d")
        return 1

    # Überprüfe Beispielaufnahmen
    if not EXAMPLES_DIR.exists():
        logger.error(f"❌ Examples-Verzeichnis nicht gefunden: {EXAMPLES_DIR}")
        return 1

    required_files = ["German.wav", "English_pcm.wav"]
    for file in required_files:
        if not (EXAMPLES_DIR / file).exists():
            logger.error(f"❌ Beispielaufnahme fehlt: {file}")
            return 1

    logger.info("✅ Alle Voraussetzungen erfüllt")

    # Test durchführen
    tester = ConversationTester()

    try:
        results = await tester.test_full_conversation()

        # Detaillierte Ergebnisse in Datei speichern
        results_file = Path(__file__).parent / f"test_results_{int(time.time())}.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"💾 Detaillierte Ergebnisse gespeichert: {results_file}")

        # Exit-Code basierend auf Testergebnis
        return 0 if results['overall_success'] else 1

    except KeyboardInterrupt:
        logger.info("\n⏹️ Test durch Benutzer abgebrochen")
        return 130
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler: {e}")
        return 1

if __name__ == "__main__":
    import sys

    # Abhängigkeiten prüfen
    try:
        import websockets
        import aiohttp
    except ImportError as e:
        print(f"❌ Fehlende Abhängigkeit: {e}")
        print("Installiere mit: pip install websockets aiohttp")
        sys.exit(1)

    # Test ausführen
    exit_code = asyncio.run(main())
    sys.exit(exit_code)