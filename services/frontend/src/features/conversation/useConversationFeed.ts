import { useEffect, useMemo, type Dispatch, type RefObject } from 'react';
import { useServices } from '@/app/providers/services';
import type { ClientRole } from '@/core/roles';
import { realtimeToChatMessage } from '@/domain/message/message.mapper';
import type { ConversationAction } from './conversation.reducer';
import { useSessionRefresh } from './useSessionRefresh';

interface ConversationFeedOptions {
  sessionId: string;
  role: ClientRole;
  dispatch: Dispatch<ConversationAction>;
  /** The autoplay hook, read through a ref so a new callback keeps the socket. */
  onPeerAudioRef: RefObject<((id: string, url: string) => void) | undefined>;
}

/** What arrives without being asked for: the history, then the gateway's pushes. */
export function useConversationFeed({
  sessionId,
  role,
  dispatch,
  onPeerAudioRef,
}: ConversationFeedOptions): void {
  const { message, createRealtime } = useServices();
  const transport = useMemo(() => createRealtime(), [createRealtime]);
  const refreshSession = useSessionRefresh(sessionId);

  useEffect(() => {
    let cancelled = false;

    void message
      .getHistory(sessionId, role)
      .then((messages) => {
        if (!cancelled) {
          dispatch({ type: 'history/loaded', messages });
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [dispatch, message, role, sessionId]);

  useEffect(() => {
    let warningExpiry: ReturnType<typeof setTimeout> | undefined;

    const offEvent = transport.onEvent((event) => {
      if (event.role === 'session_terminated') {
        dispatch({ type: 'session/ended' });
        // The gateway closes the socket next; reconnecting to an ended session only fails.
        transport.disconnect();
        return;
      }

      if (event.role === 'timeout_warning') {
        const minutes = warningMinutes(event.remaining_minutes);
        dispatch({ type: 'session/timeoutWarning', minutes });
        // No frame withdraws a warning, and an admin who reconnects extends the session.
        clearTimeout(warningExpiry);
        warningExpiry = setTimeout(
          () => dispatch({ type: 'session/timeoutWarningExpired' }),
          minutes * 60_000
        );
        return;
      }

      if (event.role === 'customer_language_changed') {
        refreshSession();
        return;
      }

      const mapped = realtimeToChatMessage(event, message.resolveAudioUrl);
      if (mapped !== null && mapped.id !== '') {
        dispatch({ type: 'realtime/message', message: mapped });

        if (mapped.origin === 'peer' && mapped.audioUrl !== null) {
          onPeerAudioRef.current?.(mapped.id, mapped.audioUrl);
        }
      }
    });

    // The gateway does not resend what it failed to deliver, so a reconnect
    // refetches: a message broadcast while the socket was down is otherwise
    // lost until the page is reloaded. The first connect is skipped — the mount
    // effect above has already loaded that history.
    let seenConnected = false;

    const offStatus = transport.onStatus((status) => {
      dispatch({ type: 'realtime/status', status });

      if (status !== 'connected') {
        return;
      }

      if (seenConnected) {
        void message
          .getHistory(sessionId, role)
          .then((messages) => dispatch({ type: 'history/reloaded', messages }))
          .catch(() => undefined);
      }

      seenConnected = true;
    });

    void transport.connect(sessionId, role);

    return () => {
      clearTimeout(warningExpiry);
      offEvent();
      offStatus();
      transport.disconnect();
    };
  }, [dispatch, message, onPeerAudioRef, refreshSession, role, sessionId, transport]);
}

/** The gateway always sends a positive whole number; anything else falls back to its default. */
function warningMinutes(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 5;
}
