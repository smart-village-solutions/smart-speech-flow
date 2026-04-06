"""
Advanced WebSocket Fallback System
Provides intelligent fallback mechanisms from WebSocket to polling with automatic
failure detection, CORS error handling, and seamless user experience.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


class FallbackReason(Enum):
    """Reasons for WebSocket fallback activation"""

    WEBSOCKET_CONNECTION_FAILED = "websocket_connection_failed"
    WEBSOCKET_HANDSHAKE_FAILED = "websocket_handshake_failed"
    CORS_ORIGIN_BLOCKED = "cors_origin_blocked"
    CORS_PREFLIGHT_FAILED = "cors_preflight_failed"
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    REPEATED_DISCONNECTS = "repeated_disconnects"
    HEARTBEAT_FAILURES = "heartbeat_failures"
    CLIENT_COMPATIBILITY = "client_compatibility"
    MANUAL_FALLBACK = "manual_fallback"


class FallbackStrategy(Enum):
    """Available fallback strategies"""

    POLLING_ONLY = "polling_only"
    POLLING_WITH_WEBSOCKET_RETRY = "polling_with_websocket_retry"
    WEBSOCKET_WITH_POLLING_BACKUP = "websocket_with_polling_backup"
    ADAPTIVE_HYBRID = "adaptive_hybrid"


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior"""

    max_websocket_retries: int = 3
    retry_intervals: List[int] = field(
        default_factory=lambda: [1, 2, 4, 8, 16]
    )  # seconds
    polling_interval: int = 5  # seconds
    fallback_timeout: int = 30  # seconds before giving up
    enable_jitter: bool = True
    jitter_max_percent: float = 0.3  # 30% jitter
    heartbeat_timeout: int = 30  # seconds
    max_consecutive_failures: int = 3
    cors_retry_delay: int = 60  # seconds before retrying WebSocket after CORS failure
    enable_user_notifications: bool = True
    enable_automatic_recovery: bool = True
    recovery_check_interval: int = 300  # 5 minutes


@dataclass
class PollingClient:
    """Represents a client using polling fallback"""

    polling_id: str
    session_id: str
    client_type: str
    origin: Optional[str]
    created_at: datetime
    last_poll: Optional[datetime] = None
    message_queue: deque = field(default_factory=deque)
    polling_interval: int = 5
    fallback_reason: FallbackReason = FallbackReason.MANUAL_FALLBACK
    retry_count: int = 0
    websocket_retry_after: Optional[datetime] = None


@dataclass
class ConnectionFailureHistory:
    """Tracks connection failure patterns"""

    failure_count: int = 0
    last_failure: Optional[datetime] = None
    failure_reasons: List[FallbackReason] = field(default_factory=list)
    cors_failures: int = 0
    network_failures: int = 0
    timeout_failures: int = 0


class WebSocketFallbackManager:
    """
    Advanced WebSocket fallback management with intelligent failure detection
    and seamless polling activation
    """

    def __init__(self, config: Optional[FallbackConfig] = None):
        self.config = config or FallbackConfig()

        # Polling clients management
        self.polling_clients: Dict[str, PollingClient] = {}
        self.session_polling_clients: Dict[str, Set[str]] = defaultdict(set)

        # Failure tracking
        self.failure_history: Dict[str, ConnectionFailureHistory] = defaultdict(
            ConnectionFailureHistory
        )

        # Statistics
        self.fallback_stats = {
            "total_fallbacks": 0,
            "active_polling_clients": 0,
            "websocket_recovery_attempts": 0,
            "successful_recoveries": 0,
            "fallback_reasons": defaultdict(int),
        }

        # Notification callbacks
        self.notification_callbacks: List[Callable] = []

        logger.info("🔄 WebSocket Fallback Manager initialized")

    def evaluate_websocket_failure(
        self,
        session_id: str,
        client_type: str,
        origin: Optional[str],
        error_details: Dict[str, Any],
    ) -> bool:
        """
        Evaluate if WebSocket failure should trigger fallback
        Returns True if fallback should be activated
        """
        origin_key = origin or "unknown_origin"
        failure_key = f"{session_id}_{client_type}_{origin_key}"
        history = self.failure_history[failure_key]

        # Determine failure reason
        reason = self._classify_failure_reason(error_details)

        # Update failure history
        history.failure_count += 1
        history.last_failure = utc_now()
        history.failure_reasons.append(reason)

        # Keep only recent failures (last 10)
        if len(history.failure_reasons) > 10:
            history.failure_reasons = history.failure_reasons[-10:]

        # Update specific failure counters
        if reason in [
            FallbackReason.CORS_ORIGIN_BLOCKED,
            FallbackReason.CORS_PREFLIGHT_FAILED,
        ]:
            history.cors_failures += 1
        elif reason == FallbackReason.NETWORK_ERROR:
            history.network_failures += 1
        elif reason == FallbackReason.TIMEOUT_ERROR:
            history.timeout_failures += 1

        # Decision logic for fallback activation
        should_fallback = self._should_activate_fallback(history, reason)

        if should_fallback:
            logger.warning(
                f"🚨 WebSocket fallback triggered for {failure_key}: {reason.value} "
                f"(failure count: {history.failure_count})"
            )

        return should_fallback

    def _classify_failure_reason(self, error_details: Dict[str, Any]) -> FallbackReason:
        """Classify the failure reason based on error details"""
        error_message = str(error_details.get("message", "")).lower()
        error_code = error_details.get("code")

        # CORS-related failures
        if "cors" in error_message or "origin" in error_message:
            if "preflight" in error_message:
                return FallbackReason.CORS_PREFLIGHT_FAILED
            return FallbackReason.CORS_ORIGIN_BLOCKED

        # WebSocket-specific failures
        if error_code in [403, 1002, 1003] or "handshake" in error_message:
            return FallbackReason.WEBSOCKET_HANDSHAKE_FAILED

        if "timeout" in error_message or error_code == 408:
            return FallbackReason.TIMEOUT_ERROR

        if "network" in error_message or error_code in [0, -1]:
            return FallbackReason.NETWORK_ERROR

        if error_code in [1006, 1011]:  # Abnormal closure, internal error
            return FallbackReason.WEBSOCKET_CONNECTION_FAILED

        # Default classification
        return FallbackReason.WEBSOCKET_CONNECTION_FAILED

    def _should_activate_fallback(
        self, history: ConnectionFailureHistory, current_reason: FallbackReason
    ) -> bool:
        """Determine if fallback should be activated based on failure history"""

        # Immediate fallback for CORS issues
        if current_reason in [
            FallbackReason.CORS_ORIGIN_BLOCKED,
            FallbackReason.CORS_PREFLIGHT_FAILED,
        ]:
            return True

        # Client compatibility issues
        if current_reason == FallbackReason.CLIENT_COMPATIBILITY:
            return True

        # Repeated failures within short timeframe
        if history.failure_count >= self.config.max_consecutive_failures:
            return True

        # Pattern analysis - consecutive same failures
        recent_failures = history.failure_reasons[-3:]  # Last 3 failures
        if len(recent_failures) >= 2 and all(
            f == current_reason for f in recent_failures
        ):
            return True

        # High frequency of different types of failures
        if history.last_failure:
            time_since_last = (utc_now() - history.last_failure).total_seconds()
            if (
                time_since_last < 30 and history.failure_count >= 2
            ):  # 2 failures in 30 seconds
                return True

        return False

    async def activate_polling_fallback(
        self,
        session_id: str,
        client_type: str,
        origin: Optional[str],
        reason: FallbackReason,
        polling_interval: Optional[int] = None,
    ) -> str:
        """Activate polling fallback for a client"""

        # Generate unique polling ID
        polling_id = f"poll_{session_id}_{client_type}_{int(time.time())}"

        # Create polling client
        polling_client = PollingClient(
            polling_id=polling_id,
            session_id=session_id,
            client_type=client_type,
            origin=origin,
            created_at=utc_now(),
            polling_interval=polling_interval or self.config.polling_interval,
            fallback_reason=reason,
        )

        # Store polling client
        self.polling_clients[polling_id] = polling_client
        self.session_polling_clients[session_id].add(polling_id)

        # Update statistics
        self.fallback_stats["total_fallbacks"] += 1
        self.fallback_stats["active_polling_clients"] = len(self.polling_clients)
        self.fallback_stats["fallback_reasons"][reason.value] += 1

        # Schedule WebSocket retry if appropriate
        if self._should_schedule_websocket_retry(reason):
            retry_delay = self._calculate_retry_delay(reason)
            polling_client.websocket_retry_after = utc_now() + timedelta(
                seconds=retry_delay
            )

            logger.info(
                f"📅 WebSocket retry scheduled in {retry_delay}s for {polling_id}"
            )

        # Send user notification
        if self.config.enable_user_notifications:
            await self._send_fallback_notification(polling_client)

        logger.info(
            f"🔄 Polling fallback activated: {polling_id} "
            f"(reason: {reason.value}, interval: {polling_client.polling_interval}s)"
        )

        return polling_id

    def send_message_to_polling_client(
        self, polling_id: str, message: Dict[str, Any]
    ) -> bool:
        """Send message to polling client's queue"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return False

        # Add message to queue with timestamp
        message_with_meta = {
            **message,
            "_polling_meta": {
                "queued_at": utc_now_iso(),
                "polling_id": polling_id,
            },
        }

        client.message_queue.append(message_with_meta)

        # Limit queue size to prevent memory issues
        if len(client.message_queue) > 100:
            client.message_queue.popleft()

        return True

    def poll_messages(self, polling_id: str) -> List[Dict[str, Any]]:
        """Retrieve queued messages for polling client"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return []

        # Update last poll time
        client.last_poll = utc_now()

        # Get all queued messages
        messages = list(client.message_queue)
        client.message_queue.clear()

        # Check if WebSocket retry should be attempted
        if self._should_attempt_websocket_retry(client):
            messages.append(
                {
                    "type": "websocket_retry_suggestion",
                    "polling_id": polling_id,
                    "retry_reason": "scheduled_recovery_attempt",
                    "timestamp": utc_now_iso(),
                }
            )

        return messages

    def attempt_websocket_recovery(self, polling_id: str) -> Dict[str, Any]:
        """Attempt to recover WebSocket connection for polling client"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return {"success": False, "error": "Polling client not found"}

        client.retry_count += 1
        self.fallback_stats["websocket_recovery_attempts"] += 1

        # Reset retry timer
        client.websocket_retry_after = None

        logger.info(
            f"🔄 Attempting WebSocket recovery for {polling_id} (attempt #{client.retry_count})"
        )

        # Return recovery attempt info for the client to handle
        return {
            "success": True,
            "polling_id": polling_id,
            "retry_count": client.retry_count,
            "recovery_info": {
                "session_id": client.session_id,
                "client_type": client.client_type,
                "origin": client.origin,
                "fallback_reason": client.fallback_reason.value,
            },
        }

    def websocket_recovery_successful(self, polling_id: str):
        """Mark WebSocket recovery as successful and cleanup polling client"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return

        # Update statistics
        self.fallback_stats["successful_recoveries"] += 1

        # Send remaining messages via WebSocket notification
        remaining_messages = list(client.message_queue)
        if remaining_messages:
            logger.info(
                f"📤 {len(remaining_messages)} queued messages will be sent via WebSocket"
            )

        # Cleanup polling client
        self._cleanup_polling_client(polling_id)

        logger.info(f"✅ WebSocket recovery successful for {polling_id}")

    def websocket_recovery_failed(
        self, polling_id: str, failure_reason: FallbackReason
    ):
        """Handle failed WebSocket recovery attempt"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return

        # Schedule next retry if within limits
        if client.retry_count < self.config.max_websocket_retries:
            retry_delay = self._calculate_retry_delay(
                failure_reason, client.retry_count
            )
            client.websocket_retry_after = utc_now() + timedelta(seconds=retry_delay)

            logger.info(
                f"⏰ Next WebSocket retry for {polling_id} scheduled in {retry_delay}s"
            )
        else:
            logger.warning(
                f"🚫 Max WebSocket retries exceeded for {polling_id}, staying in polling mode"
            )

    def deactivate_polling_fallback(self, polling_id: str) -> bool:
        """Deactivate polling fallback for a client"""
        return self._cleanup_polling_client(polling_id)

    def get_polling_client_status(self, polling_id: str) -> Optional[Dict[str, Any]]:
        """Get status information for a polling client"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return None

        return {
            "polling_id": polling_id,
            "session_id": client.session_id,
            "client_type": client.client_type,
            "origin": client.origin,
            "created_at": client.created_at.isoformat(),
            "last_poll": client.last_poll.isoformat() if client.last_poll else None,
            "polling_interval": client.polling_interval,
            "fallback_reason": client.fallback_reason.value,
            "retry_count": client.retry_count,
            "websocket_retry_after": (
                client.websocket_retry_after.isoformat()
                if client.websocket_retry_after
                else None
            ),
            "queued_messages": len(client.message_queue),
            "uptime_seconds": (utc_now() - client.created_at).total_seconds(),
        }

    def get_session_fallback_status(self, session_id: str) -> Dict[str, Any]:
        """Get fallback status for all clients in a session"""
        polling_client_ids = self.session_polling_clients.get(session_id, set())

        client_statuses = []
        for polling_id in polling_client_ids:
            status = self.get_polling_client_status(polling_id)
            if status:
                client_statuses.append(status)

        return {
            "session_id": session_id,
            "polling_clients_count": len(client_statuses),
            "polling_clients": client_statuses,
            "has_active_fallbacks": len(client_statuses) > 0,
        }

    def get_fallback_statistics(self) -> Dict[str, Any]:
        """Get comprehensive fallback system statistics"""
        active_clients_by_reason = defaultdict(int)
        active_clients_by_session = defaultdict(int)

        for client in self.polling_clients.values():
            active_clients_by_reason[client.fallback_reason.value] += 1
            active_clients_by_session[client.session_id] += 1

        return {
            **self.fallback_stats,
            "active_polling_clients": len(self.polling_clients),
            "active_sessions_with_fallback": len(self.session_polling_clients),
            "active_clients_by_reason": dict(active_clients_by_reason),
            "active_clients_by_session": dict(active_clients_by_session),
            "config": {
                "max_websocket_retries": self.config.max_websocket_retries,
                "polling_interval": self.config.polling_interval,
                "enable_automatic_recovery": self.config.enable_automatic_recovery,
                "enable_user_notifications": self.config.enable_user_notifications,
            },
        }

    # Helper methods

    def _should_schedule_websocket_retry(self, reason: FallbackReason) -> bool:
        """Determine if WebSocket retry should be scheduled"""
        # Don't retry for persistent CORS issues
        if reason == FallbackReason.CORS_ORIGIN_BLOCKED:
            return False

        # Don't retry for client compatibility issues
        if reason == FallbackReason.CLIENT_COMPATIBILITY:
            return False

        return self.config.enable_automatic_recovery

    def _calculate_retry_delay(
        self, reason: FallbackReason, retry_count: int = 0
    ) -> int:
        """Calculate delay before next retry attempt"""
        base_delays = {
            FallbackReason.CORS_PREFLIGHT_FAILED: self.config.cors_retry_delay,
            FallbackReason.NETWORK_ERROR: 5,
            FallbackReason.TIMEOUT_ERROR: 10,
            FallbackReason.WEBSOCKET_CONNECTION_FAILED: 5,
            FallbackReason.WEBSOCKET_HANDSHAKE_FAILED: 15,
        }

        base_delay = base_delays.get(reason, 10)

        # Exponential backoff for multiple retries
        if retry_count > 0 and retry_count < len(self.config.retry_intervals):
            base_delay = self.config.retry_intervals[retry_count]

        # Add jitter if enabled
        if self.config.enable_jitter:
            import random

            jitter = random.uniform(
                -self.config.jitter_max_percent, self.config.jitter_max_percent
            )
            base_delay = int(base_delay * (1 + jitter))

        return max(1, base_delay)

    def _should_attempt_websocket_retry(self, client: PollingClient) -> bool:
        """Check if WebSocket retry should be attempted"""
        if not client.websocket_retry_after:
            return False

        if utc_now() < client.websocket_retry_after:
            return False

        if client.retry_count >= self.config.max_websocket_retries:
            return False

        return True

    async def _send_fallback_notification(self, client: PollingClient):
        """Send notification about fallback activation"""
        notification = {
            "type": "fallback_notification",
            "polling_id": client.polling_id,
            "fallback_reason": client.fallback_reason.value,
            "message": self._get_user_friendly_message(client.fallback_reason),
            "polling_interval": client.polling_interval,
            "recovery_info": {
                "automatic_retry": self._should_schedule_websocket_retry(
                    client.fallback_reason
                ),
                "retry_after": (
                    client.websocket_retry_after.isoformat()
                    if client.websocket_retry_after
                    else None
                ),
            },
            "timestamp": utc_now_iso(),
        }

        # Add to message queue
        client.message_queue.append(notification)

        # Call notification callbacks
        for callback in self.notification_callbacks:
            try:
                await callback(notification)
            except Exception as e:
                logger.error(f"Error in notification callback: {e}")

    def _get_user_friendly_message(self, reason: FallbackReason) -> str:
        """Get user-friendly message for fallback reason"""
        messages = {
            FallbackReason.CORS_ORIGIN_BLOCKED: "Connection switched to compatibility mode due to security restrictions. Functionality remains available.",
            FallbackReason.CORS_PREFLIGHT_FAILED: "Connection using compatibility mode due to browser security settings. All features are still accessible.",
            FallbackReason.NETWORK_ERROR: "Connection adapted to compatibility mode due to network conditions. Service continues normally.",
            FallbackReason.WEBSOCKET_CONNECTION_FAILED: "Connection using alternative mode for optimal compatibility. All features remain available.",
            FallbackReason.TIMEOUT_ERROR: "Connection switched to reliable mode due to network timing. Service quality maintained.",
            FallbackReason.CLIENT_COMPATIBILITY: "Using compatibility mode optimized for your browser. Full functionality available.",
        }

        return messages.get(
            reason,
            "Connection using compatibility mode. All features remain available.",
        )

    def _cleanup_polling_client(self, polling_id: str) -> bool:
        """Remove polling client and cleanup resources"""
        client = self.polling_clients.get(polling_id)
        if not client:
            return False

        # Remove from session tracking
        session_clients = self.session_polling_clients.get(client.session_id, set())
        session_clients.discard(polling_id)

        if not session_clients:
            del self.session_polling_clients[client.session_id]

        # Remove client
        del self.polling_clients[polling_id]

        # Update statistics
        self.fallback_stats["active_polling_clients"] = len(self.polling_clients)

        logger.info(f"🧹 Polling client cleaned up: {polling_id}")
        return True

    async def periodic_cleanup(self):
        """Periodic cleanup of stale polling clients"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                now = utc_now()
                stale_clients = []

                for polling_id, client in self.polling_clients.items():
                    # Consider client stale if no activity for 30 minutes
                    last_activity = client.last_poll or client.created_at
                    if (now - last_activity).total_seconds() > 1800:  # 30 minutes
                        stale_clients.append(polling_id)

                # Cleanup stale clients
                for polling_id in stale_clients:
                    self._cleanup_polling_client(polling_id)

                if stale_clients:
                    logger.info(
                        f"🧹 Cleaned up {len(stale_clients)} stale polling clients"
                    )

            except Exception as e:
                logger.error(f"Error in polling cleanup task: {e}")


# Global Fallback Manager Instance
fallback_manager = WebSocketFallbackManager()
