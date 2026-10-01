"""The gateway's long-running loops: session timeouts, socket monitoring, health polling, retention."""

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .audio_storage import AudioStore


# === Background Tasks ===
async def session_timeout_monitor(session_manager: Any) -> None:
    """Background Task für Session-Timeout-Management"""
    while True:
        try:
            await session_manager.check_session_timeouts()
            await asyncio.sleep(60)  # Alle 60 Sekunden prüfen
        except Exception as e:
            print(f"⚠️ Fehler im Session-Timeout-Monitor: {e}")
            await asyncio.sleep(60)


async def websocket_monitor_task(monitor: Any, manager: Any) -> None:
    """Background Task für WebSocket-Monitoring und Cleanup"""
    await asyncio.sleep(1)  # Kurz warten bis Startup abgeschlossen

    print("🚀 WebSocket-Monitoring gestartet")
    await monitor.periodic_cleanup(lambda: manager.all_connections.keys())


async def circuit_breaker_monitor(circuit_breaker_client: Any) -> None:
    """Starts the service health polling for the lifespan.

    The cleanup loop that used to live here swept an expired-response cache
    and a request queue, both of which went with the fallback machinery in
    #219. ServiceHealthManager owns its own polling task, so there is nothing
    left for this one to do after starting it.
    """
    await circuit_breaker_client.start_health_monitoring()
    print("🚀 Circuit Breaker Health Monitoring gestartet")


async def audio_cleanup_task(session_manager: Any, audio_store: "AudioStore") -> None:
    """Background Task für automatisches Löschen alter Inhalte (Retention)"""
    from .session_manager import utc_now

    print("🧹 Audio-Cleanup-Service gestartet (läuft stündlich)")

    while True:
        try:
            # Stündliche Cleanup-Routine
            await asyncio.sleep(3600)  # 1 Stunde warten

            # Cleanup durchführen
            stats = audio_store.cleanup_expired()
            print(f"🧹 Audio-Cleanup abgeschlossen: {stats['total_deleted']} Dateien gelöscht")

            # Transcripts expire on the same pass. Audio alone would keep
            # the weaker half of the promise.
            content = session_manager.sweep_expired_content(utc_now())
            print(
                "🧹 Content-Sweep abgeschlossen: "
                f"{content['refused_removed']} abgelehnt, "
                f"{content['expired_removed']} abgelaufen"
            )

            # Disk Usage loggen
            disk_stats = audio_store.disk_usage()
            total_mb = disk_stats["total_bytes"] / (1024 * 1024)
            print(f"💾 Audio Storage: {disk_stats['total_files']} Dateien, {total_mb:.2f} MB")

        except Exception as e:
            # One failed pass must not end retention; the next pass is an hour away.
            print(f"⚠️ Fehler im Audio-Cleanup-Task: {type(e).__name__}")
