import type { ClientRole } from '@/core/roles';

export type RealtimeStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

/** A gateway push. `role` discriminates; see the WS contract in SCREEN_SPECS.md. */
export interface RealtimeEvent {
  role: string;
  [key: string]: unknown;
}

export interface RealtimeTransport {
  connect(sessionId: string, role: ClientRole): void;
  disconnect(): void;
  send(payload: Record<string, unknown>): void;
  /** Returns an unsubscribe function. */
  onEvent(handler: (event: RealtimeEvent) => void): () => void;
  /** Returns an unsubscribe function. */
  onStatus(handler: (status: RealtimeStatus) => void): () => void;
  getStatus(): RealtimeStatus;
}
