import type { RealtimeStatus } from '@/core/realtime/realtime.port';

export interface StatusSnapshot {
  ended: boolean;
  /** Minutes until the gateway ends the session for inactivity, when it has warned. */
  timeoutWarning: number | null;
  connection: RealtimeStatus;
  /** False until the socket has connected once; see the reducer. */
  hasConnected: boolean;
  errorKey: string | null;
}

/**
 * Whether the status pill will say anything. The chat stack reserves room for
 * the pill, so it needs the same answer without rendering it.
 *
 * A first connect is deliberately silent: the handshake on opening the screen
 * is not a reconnection, and announcing it would flash a notice on every load.
 */
export function hasConversationStatus({
  ended,
  timeoutWarning,
  connection,
  hasConnected,
  errorKey,
}: StatusSnapshot): boolean {
  return (
    ended ||
    errorKey !== null ||
    timeoutWarning !== null ||
    (hasConnected && connection !== 'connected')
  );
}
