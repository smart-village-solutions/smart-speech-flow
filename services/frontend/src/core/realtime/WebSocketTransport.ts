import { buildWebSocketUrl } from '@/utils/identifiers';
import type { ClientRole } from '@/core/roles';
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
  issueAdminTicket: (sessionId: string, transport: 'websocket') => Promise<string>;
  createSocket?: (url: string) => WebSocketLike;
  maxReconnectAttempts?: number;
  reconnectDelayMs?: number;
  heartbeatIntervalMs?: number;
}

const CONNECTING = 0;
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
    issueAdminTicket,
    createSocket = (url) => new WebSocket(url) as unknown as WebSocketLike,
    maxReconnectAttempts = 5,
    reconnectDelayMs = 1000,
    heartbeatIntervalMs = 30_000,
  } = options;

  const eventHandlers = new Set<(event: RealtimeEvent) => void>();
  const statusHandlers = new Set<(status: RealtimeStatus) => void>();

  let socket: WebSocketLike | null = null;
  let sessionId: string | null = null;
  let role: ClientRole | null = null;
  let status: RealtimeStatus = 'disconnected';
  let reconnectAttempts = 0;
  let intentionallyClosed = false;
  let heartbeatId: ReturnType<typeof setInterval> | null = null;
  let reconnectId: ReturnType<typeof setTimeout> | null = null;
  let generation = 0;

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

  function scheduleReconnect(expectedGeneration: number): void {
    if (intentionallyClosed || sessionId === null) {
      return;
    }

    if (reconnectAttempts >= maxReconnectAttempts) {
      setStatus('error');
      return;
    }

    reconnectAttempts += 1;
    const delay = reconnectDelayMs * reconnectAttempts;
    reconnectId = setTimeout(() => {
      reconnectId = null;
      if (sessionId !== null && generation === expectedGeneration) {
        void open(sessionId, role as ClientRole, expectedGeneration);
      }
    }, delay);
  }

  async function open(
    id: string,
    connectionRole: ClientRole,
    expectedGeneration: number
  ): Promise<void> {
    if (intentionallyClosed || generation !== expectedGeneration) {
      return;
    }
    setStatus('connecting');
    let ticket: string | undefined;
    if (connectionRole === 'admin') {
      try {
        ticket = await issueAdminTicket(id, 'websocket');
      } catch {
        if (!intentionallyClosed && generation === expectedGeneration) {
          setStatus('error');
          scheduleReconnect(expectedGeneration);
        }
        return;
      }
    }

    // Ticket issuance is asynchronous. A route change or StrictMode cleanup
    // may have invalidated this connection while the HTTP request was in
    // flight; in that case the single-use ticket is deliberately abandoned.
    if (
      intentionallyClosed ||
      generation !== expectedGeneration ||
      sessionId !== id ||
      role !== connectionRole
    ) {
      return;
    }

    const next = createSocket(buildWebSocketUrl(wsBaseUrl, id, connectionRole, ticket));

    // Close events arrive after the fact, so a socket this transport has since
    // replaced can still call back. Every handler answers for its own socket
    // only: the alternative is a superseded close stopping the live socket's
    // heartbeat and reconnecting past it, leaving that connection open on the
    // gateway. A remount — StrictMode does one on every mount — is enough.
    const isCurrent = () => socket === next;

    // A successful open clears the budget, so it counts consecutive failures.
    next.onopen = () => {
      if (!isCurrent()) {
        return;
      }
      reconnectAttempts = 0;
      setStatus('connected');
      startHeartbeat();
    };

    next.onmessage = (event) => {
      if (!isCurrent()) {
        return;
      }

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

    next.onerror = () => {
      if (isCurrent()) {
        setStatus('error');
      }
    };

    next.onclose = () => {
      if (!isCurrent()) {
        return;
      }

      stopHeartbeat();
      if (!intentionallyClosed) {
        setStatus('disconnected');
        scheduleReconnect(expectedGeneration);
      }
    };

    socket = next;
  }

  return {
    async connect(id, clientRole) {
      // A socket still negotiating is a connection in progress, not an absent
      // one; opening a second would leak the first.
      if (socket !== null && (socket.readyState === OPEN || socket.readyState === CONNECTING)) {
        return;
      }
      if (status === 'connecting') {
        return;
      }
      intentionallyClosed = false;
      reconnectAttempts = 0;
      sessionId = id;
      role = clientRole;
      generation += 1;
      await open(id, clientRole, generation);
    },

    disconnect() {
      intentionallyClosed = true;
      generation += 1;
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
