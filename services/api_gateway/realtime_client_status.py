"""Device status a socket reports, and the polling interval it earns.

A tab, battery or network report changes only the reporting socket's own
interval, and the reply goes to that socket alone.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .realtime_connection import WebSocketConnection, safe_identifier
from .realtime_protocol import battery_saver_frame, polling_interval_update_frame

# The manager's own logger, so these log lines keep their logger name.
logger = logging.getLogger("services.api_gateway.websocket")


class AdaptivePollingManager:
    """
    📱 Mobile-optimiertes adaptives Polling-System
    Passt Polling-Intervalle basierend auf Device-Status an
    """

    # Polling-Intervall-Konfiguration (Sekunden)
    POLLING_INTERVALS = {
        "active_desktop": 3,  # Sehr responsiv für Desktop
        "active_mobile": 5,  # Standard responsiv für Mobile
        "background_desktop": 10,  # Reduziert für Desktop-Background
        "background_mobile": 30,  # Stark reduziert für Mobile-Background
        "battery_saver": 60,  # Minimal für Battery-Saver-Mode
        "slow_network": 15,  # Angepasst für langsame Verbindungen
        "offline_mode": 120,  # Sehr selten für Offline-Detection
    }

    def get_optimal_interval(self, connection: WebSocketConnection) -> int:
        """
        Berechnet optimales Polling-Intervall basierend auf Client-Status
        """
        # Battery-Saver hat höchste Priorität
        if connection.battery_level < 0.2:  # <20% Battery
            return self.POLLING_INTERVALS["battery_saver"]

        # Network-Quality berücksichtigen
        if connection.network_quality == "slow":
            return self.POLLING_INTERVALS["slow_network"]
        elif connection.network_quality == "offline":
            return self.POLLING_INTERVALS["offline_mode"]

        # Mobile vs Desktop + Tab-Status
        if connection.is_mobile:
            if connection.tab_active:
                return self.POLLING_INTERVALS["active_mobile"]
            else:
                return self.POLLING_INTERVALS["background_mobile"]
        else:
            if connection.tab_active:
                return self.POLLING_INTERVALS["active_desktop"]
            else:
                return self.POLLING_INTERVALS["background_desktop"]

    def update_client_status(
        self,
        connection: WebSocketConnection,
        is_mobile: Optional[bool] = None,
        tab_active: Optional[bool] = None,
        battery_level: Optional[float] = None,
        network_quality: Optional[str] = None,
    ) -> int:
        """
        Client-Status aktualisieren und neues Intervall zurückgeben
        """
        if is_mobile is not None:
            connection.is_mobile = is_mobile
        if tab_active is not None:
            connection.tab_active = tab_active
        if battery_level is not None:
            connection.battery_level = max(0.0, min(1.0, battery_level))
        if network_quality is not None:
            connection.network_quality = network_quality

        # Neues optimales Intervall berechnen
        new_interval = self.get_optimal_interval(connection)
        connection.current_polling_interval = new_interval

        return new_interval

    def get_battery_optimization_tips(self, connection: WebSocketConnection) -> List[str]:
        """
        Battery-Optimierungs-Tipps für Client
        """
        tips = []

        if connection.battery_level < 0.3:
            tips.append("🔋 Niedriger Akkustand - Polling-Intervall auf 60s erhöht")

        if not connection.tab_active and connection.is_mobile:
            tips.append("📱 Tab im Hintergrund - Reduzierte Update-Frequenz aktiviert")

        if connection.network_quality == "slow":
            tips.append("📶 Langsame Verbindung erkannt - Polling angepasst")

        return tips


class ClientStatusHandler:
    """Answers a socket's tab, battery and network reports."""

    def __init__(self, adaptive_polling: AdaptivePollingManager) -> None:
        self.adaptive_polling = adaptive_polling

    async def handle_tab_visibility_change(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ) -> None:
        """
        Tab-Visibility-Change verarbeiten (Background/Foreground)
        """
        is_visible = message.get("is_visible", True)
        old_interval = connection.current_polling_interval

        # Status aktualisieren und neues Intervall berechnen
        new_interval = self.adaptive_polling.update_client_status(connection, tab_active=is_visible)

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            await self.send_polling_interval_update(
                connection,
                new_interval,
                reason=("tab_visibility_change" if is_visible else "background_optimization"),
            )

        logger.info(
            "websocket_tab_visibility_changed session_ref=%s",
            safe_identifier(connection.session_id),
        )

    async def handle_battery_status_update(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ) -> None:
        """
        Battery-Status-Update verarbeiten
        """
        battery_level = message.get("battery_level", 1.0)
        is_charging = message.get("is_charging", False)
        old_interval = connection.current_polling_interval

        # Status aktualisieren
        new_interval = self.adaptive_polling.update_client_status(
            connection, battery_level=battery_level
        )

        # Battery-Saver-Mode Detection
        if battery_level < 0.2 and not is_charging:
            await self.send_battery_saver_notification(connection)

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            await self.send_polling_interval_update(
                connection, new_interval, reason="battery_optimization"
            )

        logger.info(
            "websocket_battery_status_changed session_ref=%s",
            safe_identifier(connection.session_id),
        )

    async def handle_network_status_change(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ) -> None:
        """
        Network-Status-Change verarbeiten
        """
        network_quality = message.get("network_quality", "good")  # "good", "slow", "offline"
        old_interval = connection.current_polling_interval

        # Status aktualisieren
        new_interval = self.adaptive_polling.update_client_status(
            connection, network_quality=network_quality
        )

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            reason = f"network_{network_quality}"
            await self.send_polling_interval_update(connection, new_interval, reason=reason)

        logger.info(
            "websocket_network_status_changed session_ref=%s",
            safe_identifier(connection.session_id),
        )

    async def send_polling_interval_update(
        self, connection: WebSocketConnection, new_interval: int, reason: str
    ) -> None:
        """
        Polling-Intervall-Update an Client senden
        """
        optimization_tips = self.adaptive_polling.get_battery_optimization_tips(connection)

        message = polling_interval_update_frame(
            new_interval=new_interval,
            old_interval=connection.current_polling_interval,
            reason=reason,
            optimization_tips=optimization_tips,
            battery_level=connection.battery_level,
            is_mobile=connection.is_mobile,
            tab_active=connection.tab_active,
        )

        try:
            await connection.websocket.send_json(message)
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Senden des Polling-Updates: {e}")

    async def send_battery_saver_notification(self, connection: WebSocketConnection) -> None:
        """
        Battery-Saver-Notification an Client senden
        """
        message = battery_saver_frame(connection.battery_level)

        try:
            await connection.websocket.send_json(message)
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Senden der Battery-Saver-Notification: {e}")
