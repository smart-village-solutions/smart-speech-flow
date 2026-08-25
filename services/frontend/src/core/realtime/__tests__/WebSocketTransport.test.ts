import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createWebSocketTransport } from '@/core/realtime/WebSocketTransport';
import type { WebSocketLike } from '@/core/realtime/WebSocketTransport';
import type { RealtimeEvent, RealtimeStatus } from '@/core/realtime/realtime.port';

class FakeSocket implements WebSocketLike {
  static readonly instances: FakeSocket[] = [];
  readonly url: string;
  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  drop(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function makeTransport() {
  const statuses: RealtimeStatus[] = [];
  const events: RealtimeEvent[] = [];
  const transport = createWebSocketTransport({
    wsBaseUrl: 'ws://api.test',
    createSocket: (url) => new FakeSocket(url),
    reconnectDelayMs: 1000,
    heartbeatIntervalMs: 30_000,
    maxReconnectAttempts: 2,
  });
  transport.onStatus((status) => statuses.push(status));
  transport.onEvent((event) => events.push(event));
  return { transport, statuses, events };
}

function lastSocket(): FakeSocket {
  const socket = FakeSocket.instances.at(-1);
  if (socket === undefined) {
    throw new Error('no socket was created');
  }
  return socket;
}

beforeEach(() => {
  FakeSocket.instances.length = 0;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('createWebSocketTransport', () => {
  it('builds the customer socket URL from the session id', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');

    expect(FakeSocket.instances[0].url).toBe('ws://api.test/ws/A1B2C3D4/customer');
  });

  it('reports connecting then connected', () => {
    const { transport, statuses } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();

    expect(statuses).toEqual(['connecting', 'connected']);
  });

  it('dispatches parsed events to subscribers', () => {
    const { transport, events } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].receive({ role: 'receiver_message', text: 'hi' });

    expect(events).toEqual([{ role: 'receiver_message', text: 'hi' }]);
  });

  it('ignores payloads that are not valid JSON', () => {
    const { transport, events } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].onmessage?.({ data: 'not json' });

    expect(events).toEqual([]);
  });

  // The gateway refreshes last_heartbeat only for `heartbeat_pong`
  // (api_gateway/websocket.py:923) and closes the socket 60s after the last
  // refresh. Any other type is logged as unknown and refreshes nothing, so the
  // wording of these messages is load-bearing, not cosmetic.
  it('sends the heartbeat the gateway recognises, on the configured interval', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    vi.advanceTimersByTime(30_000);

    expect(FakeSocket.instances[0].sent).toEqual([JSON.stringify({ type: 'heartbeat_pong' })]);
  });

  it('answers the gateway heartbeat ping at once, without waiting for the interval', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].receive({ type: 'heartbeat_ping', timestamp: '2026-08-24T10:00:00Z' });

    expect(FakeSocket.instances[0].sent).toEqual([JSON.stringify({ type: 'heartbeat_pong' })]);
  });

  it('keeps heartbeat pings out of the conversation', () => {
    const { transport, events } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].receive({ type: 'heartbeat_ping' });

    expect(events).toEqual([]);
  });

  it('reconnects after an unexpected close', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].drop();
    vi.advanceTimersByTime(1000);

    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('resets the attempt budget once a reconnect succeeds', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();

    // Four drops, each followed by a socket that opens successfully. Because a
    // successful open clears the counter, the budget of 2 is never spent.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      lastSocket().drop();
      vi.advanceTimersByTime(10_000);
      lastSocket().open();
    }

    expect(FakeSocket.instances).toHaveLength(5);
    expect(transport.getStatus()).toBe('connected');
  });

  it('stops reconnecting once the attempt budget is spent', () => {
    const { transport, statuses } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();

    // No socket opens after the first, so the failures are consecutive.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      lastSocket().drop();
      vi.advanceTimersByTime(10_000);
    }

    expect(FakeSocket.instances).toHaveLength(3);
    expect(statuses.at(-1)).toBe('error');
  });

  it('does not reconnect after an explicit disconnect', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    transport.disconnect();
    FakeSocket.instances[0].drop(1000);
    vi.advanceTimersByTime(10_000);

    expect(FakeSocket.instances).toHaveLength(1);
  });

  // A remount — StrictMode does one on every mount — disconnects and reconnects
  // the same transport. The first socket's close event arrives after the second
  // is already open, and must not be mistaken for the live socket dropping.
  it('ignores the close of a socket it has already replaced', () => {
    const { transport, statuses } = makeTransport();
    transport.connect('A1B2C3D4');
    const first = FakeSocket.instances[0];
    first.open();

    transport.disconnect();
    transport.connect('A1B2C3D4');
    const second = FakeSocket.instances[1];
    second.open();

    statuses.length = 0;
    first.drop();
    vi.advanceTimersByTime(10_000);

    expect(statuses).toEqual([]);
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('keeps the live socket beating when a replaced socket closes', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    const first = FakeSocket.instances[0];
    first.open();

    transport.disconnect();
    transport.connect('A1B2C3D4');
    const second = FakeSocket.instances[1];
    second.open();

    first.drop();
    vi.advanceTimersByTime(30_000);

    expect(second.sent.map((payload) => JSON.parse(payload).type)).toContain('heartbeat_pong');
  });

  it('opens no second socket while the first is still connecting', () => {
    const { transport } = makeTransport();
    transport.connect('A1B2C3D4');
    transport.connect('A1B2C3D4');

    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('unsubscribes cleanly', () => {
    const { transport } = makeTransport();
    const seen: RealtimeEvent[] = [];
    const unsubscribe = transport.onEvent((event) => seen.push(event));
    transport.connect('A1B2C3D4');
    FakeSocket.instances[0].open();
    unsubscribe();
    FakeSocket.instances[0].receive({ role: 'error' });

    expect(seen).toEqual([]);
  });
});
