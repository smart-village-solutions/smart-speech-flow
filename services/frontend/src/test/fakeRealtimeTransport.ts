import type { RealtimeTransport } from '@/core/realtime/realtime.port';

/** A deliberately inert transport for UI tests that do not exercise realtime. */
export function createFakeRealtimeTransport(): RealtimeTransport {
  return {
    connect: async () => {},
    disconnect: () => {},
    send: () => {},
    onEvent: () => () => {},
    onStatus: () => () => {},
    getStatus: () => 'disconnected',
  };
}
