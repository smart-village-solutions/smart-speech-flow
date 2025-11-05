#!/usr/bin/env python3
"""
Load Test: Multiple concurrent sessions broadcasting simultaneously
Tests WebSocketManager unter Last mit parallelen Sessions
"""

import asyncio
import aiohttp
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

async def create_session_and_broadcast(session_num: int, num_messages: int = 3):
    """Erstellt eine Session und sendet mehrere Nachrichten"""
    try:
        async with aiohttp.ClientSession() as http_session:
            # Admin Session erstellen
            async with http_session.post(f"{BASE_URL}/api/admin/session/create") as resp:
                if resp.status not in [200, 201]:
                    logger.error(f"Session {session_num}: Failed to create admin session (status {resp.status})")
                    return False
                data = await resp.json()
                session_id = data['session_id']
                logger.info(f"Session {session_num}: Created {session_id}")

            # Customer aktivieren
            async with http_session.post(
                f"{BASE_URL}/api/session/{session_id}/activate",
                json={"language": "en"}
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Session {session_num}: Failed to activate")
                    return False

            # WebSocket Connections
            admin_ws = None
            customer_ws = None
            try:
                admin_ws = await http_session.ws_connect(f"{WS_URL}/ws/{session_id}/admin")
                customer_ws = await http_session.ws_connect(f"{WS_URL}/ws/{session_id}/customer")

                # CONNECTION_ACK empfangen
                await admin_ws.receive_json()
                await customer_ws.receive_json()

                logger.info(f"Session {session_num}: WebSockets connected")

                # Mehrere Nachrichten senden
                for i in range(num_messages):
                    async with http_session.post(
                        f"{BASE_URL}/api/session/{session_id}/message",
                        json={
                            "text": f"Test message {i+1} from session {session_num}",
                            "source_lang": "en",
                            "target_lang": "de",
                            "client_type": "admin"
                        }
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Session {session_num}: Message {i+1} sent")
                        else:
                            logger.error(f"Session {session_num}: Message {i+1} failed")

                    # Kurze Pause zwischen Messages
                    await asyncio.sleep(0.5)

                # Warte auf Broadcasts
                await asyncio.sleep(2)

                logger.info(f"Session {session_num}: ✅ Completed successfully")
                return True

            finally:
                if admin_ws:
                    await admin_ws.close()
                if customer_ws:
                    await customer_ws.close()

    except Exception as e:
        logger.error(f"Session {session_num}: ❌ Error: {e}")
        return False

async def run_load_test(num_sessions: int = 5, messages_per_session: int = 3):
    """Führt Load Test mit mehreren parallelen Sessions aus"""
    logger.info(f"🚀 Starting load test: {num_sessions} sessions, {messages_per_session} messages each")
    logger.info(f"Total broadcasts expected: {num_sessions * messages_per_session}")

    start_time = datetime.now()

    # Alle Sessions parallel ausführen
    tasks = [
        create_session_and_broadcast(i, messages_per_session)
        for i in range(1, num_sessions + 1)
    ]

    results = await asyncio.gather(*tasks)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Ergebnisse
    successful = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)

    logger.info(f"\n{'='*60}")
    logger.info(f"📊 LOAD TEST RESULTS")
    logger.info(f"{'='*60}")
    logger.info(f"Sessions: {num_sessions}")
    logger.info(f"Messages per session: {messages_per_session}")
    logger.info(f"Total messages: {num_sessions * messages_per_session}")
    logger.info(f"Successful sessions: {successful}")
    logger.info(f"Failed sessions: {failed}")
    logger.info(f"Duration: {duration:.2f}s")
    logger.info(f"Throughput: {(num_sessions * messages_per_session) / duration:.2f} msg/s")
    logger.info(f"{'='*60}")

    return successful == num_sessions

if __name__ == "__main__":
    success = asyncio.run(run_load_test(num_sessions=5, messages_per_session=3))
    exit(0 if success else 1)
