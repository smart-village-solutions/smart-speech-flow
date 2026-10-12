import { act } from '@testing-library/react';
import { vi } from 'vitest';
import type {
  RealtimeEvent,
  RealtimeStatus,
  RealtimeTransport,
} from '@/core/realtime/realtime.port';

/** A transport the test pushes gateway events and connection changes through by hand. */
export function createRealtimeWire() {
  const handlers: ((event: RealtimeEvent) => void)[] = [];
  const statusHandlers: ((status: RealtimeStatus) => void)[] = [];

  const transport: RealtimeTransport = {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    send: vi.fn(),
    onEvent: (handler) => {
      handlers.push(handler);
      return () => handlers.splice(handlers.indexOf(handler), 1);
    },
    onStatus: (handler) => {
      statusHandlers.push(handler);
      return () => statusHandlers.splice(statusHandlers.indexOf(handler), 1);
    },
    getStatus: () => 'connected',
  };

  return {
    transport,
    async receive(event: RealtimeEvent) {
      await act(async () => {
        handlers.forEach((handler) => handler(event));
      });
    },
    async status(next: RealtimeStatus) {
      await act(async () => {
        statusHandlers.forEach((handler) => handler(next));
      });
    },
  };
}
