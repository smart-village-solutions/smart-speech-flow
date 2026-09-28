"""One live WebSocket and what the realtime collaborators record about it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket

from .realtime_protocol import ConnectionState
from .session_manager import ClientType
from .tenant_session import TenantSessionKey


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        return dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def safe_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


@dataclass
class WebSocketConnection:
    """WebSocket-Verbindung mit Metadata"""

    websocket: WebSocket
    client_type: ClientType
    session_id: str
    connected_at: datetime
    last_heartbeat: datetime
    key: TenantSessionKey
    state: ConnectionState = ConnectionState.CONNECTING
    reconnect_count: int = 0
    client_info: Optional[Dict[str, Any]] = None
    # The outstanding ping. Latency is measured only for a pong that echoes its
    # ping_id: both clients also send pongs on their own timer, and the legacy
    # client never answers a ping at all.
    pending_ping_id: Optional[str] = None
    ping_sent_at: Optional[datetime] = None

    # 📱 Mobile-Optimization Fields
    is_mobile: bool = False
    tab_active: bool = True
    battery_level: float = 1.0
    network_quality: str = "good"  # "good", "slow", "offline"
    current_polling_interval: int = 5  # Sekunden

    def is_alive(self) -> bool:
        """Prüft ob die Verbindung noch aktiv ist"""
        if self.state in [ConnectionState.DISCONNECTED, ConnectionState.ERROR]:
            return False

        # Heartbeat-Timeout prüfen (60 Sekunden)
        timeout_threshold = utc_now() - timedelta(seconds=60)
        return ensure_utc(self.last_heartbeat) > timeout_threshold

    def to_dict(self) -> Dict[str, Any]:
        """Serialisierung für Monitoring"""
        return {
            "client_type": self.client_type.value,
            "session_id": self.session_id,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "state": self.state.value,
            "reconnect_count": self.reconnect_count,
            # 📱 Mobile-Optimization Info
            "is_mobile": self.is_mobile,
            "tab_active": self.tab_active,
            "battery_level": self.battery_level,
            "network_quality": self.network_quality,
            "current_polling_interval": self.current_polling_interval,
            "is_alive": self.is_alive(),
            "client_info": self.client_info,
        }
