import { buildWebSocketUrl } from '@/utils/identifiers';
import type { RealtimeEvent, RealtimeStatus, RealtimeTransport } from './realtime.port';

/** The subset of WebSocket this transport uses, so tests can supply a fake. */
export interface WebSocketLike {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
}

export interface WebSocketTransportOptions {
  wsBaseUrl: string;
  createSocket?: (url: string) => WebSocketLike;
  maxReconnectAttempts?: number;
  reconnectDelayMs?: number;
  heartbeatIntervalMs?: number;
}

const OPEN = 1;

/**
 * The gateway refreshes `last_heartbeat` only when it receives this exact type
 * (`api_gateway/websocket.py:923`) and closes the socket 60 seconds after the
 * last refresh. Anything else is logged as an unknown type and refreshes
 * nothing, which silently kills the connection every minute.
 */
const HEARTBEAT_PONG = 'heartbeat_pong';
const HEARTBEAT_PING = 'heartbeat_ping';

export function createWebSocketTransport(options: WebSocketTransportOptions): RealtimeTransport {
  const {
    wsBaseUrl,
    createSocket = (url) => new WebSocket(url) as unknown as WebSocketLike,
    maxReconnectAttempts = 5,
    reconnectDelayMs = 1000,
    heartbeatIntervalMs = 30_000,
  } = options;

  const eventHandlers = new Set<(event: RealtimeEvent) => void>();
  const statusHandlers = new Set<(status: RealtimeStatus) => void>();

  let socket: WebSocketLike | null = null;
  let sessionId: string | null = null;
  let status: RealtimeStatus = 'disconnected';
  let reconnectAttempts = 0;
  let intentionallyClosed = false;
  let heartbeatId: ReturnType<typeof setInterval> | null = null;
  let reconnectId: ReturnType<typeof setTimeout> | null = null;

  function setStatus(next: RealtimeStatus): void {
    status = next;
    statusHandlers.forEach((handler) => handler(next));
  }

  function stopHeartbeat(): void {
    if (heartbeatId !== null) {
      clearInterval(heartbeatId);
      heartbeatId = null;
    }
  }

  function sendPong(): void {
    if (socket?.readyState === OPEN) {
      socket.send(JSON.stringify({ type: HEARTBEAT_PONG }));
    }
  }

  // Belt and braces: answer every ping, and keep an unsolicited beat of our own
  // so a stalled ping loop on the gateway cannot time the connection out.
  function startHeartbeat(): void {
    stopHeartbeat();
    heartbeatId = setInterval(sendPong, heartbeatIntervalMs);
  }

  function scheduleReconnect(): void {
    if (intentionallyClosed || sessionId === null) {
      return;
    }

    if (reconnectAttempts >= maxReconnectAttempts) {
      setStatus('error');
      return;
    }

    reconnectAttempts += 1;
    const delay = reconnectDelayMs * reconnectAttempts;
    reconnectId = setTimeout(() => open(sessionId as string), delay);
  }

  function open(id: string): void {
    setStatus('connecting');
    const next = createSocket(buildWebSocketUrl(wsBaseUrl, id, 'customer'));

    // A successful open clears the budget, so it counts consecutive failures.
    next.onopen = () => {
      reconnectAttempts = 0;
      setStatus('connected');
      startHeartbeat();
    };

    next.onmessage = (event) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }

      if (typeof parsed !== 'object' || parsed === null) {
        return;
      }

      if ((parsed as { type?: string }).type === HEARTBEAT_PING) {
        sendPong();
        return;
      }

      if ('role' in parsed) {
        eventHandlers.forEach((handler) => handler(parsed as RealtimeEvent));
      }
    };

    next.onerror = () => setStatus('error');

    next.onclose = () => {
      stopHeartbeat();
      if (!intentionallyClosed) {
        setStatus('disconnected');
        scheduleReconnect();
      }
    };

    socket = next;
  }

  return {
    connect(id) {
      if (socket?.readyState === OPEN) {
        return;
      }
      intentionallyClosed = false;
      reconnectAttempts = 0;
      sessionId = id;
      open(id);
    },

    disconnect() {
      intentionallyClosed = true;
      stopHeartbeat();
      if (reconnectId !== null) {
        clearTimeout(reconnectId);
        reconnectId = null;
      }
      socket?.close();
      socket = null;
      setStatus('disconnected');
    },

    send(payload) {
      if (socket?.readyState === OPEN) {
        socket.send(JSON.stringify(payload));
      }
    },

    onEvent(handler) {
      eventHandlers.add(handler);
      return () => eventHandlers.delete(handler);
    },

    onStatus(handler) {
      statusHandlers.add(handler);
      return () => statusHandlers.delete(handler);
    },

    getStatus: () => status,
  };
}
