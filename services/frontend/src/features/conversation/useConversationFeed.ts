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
    const offEvent = transport.onEvent((event) => {
      if (event.role === 'session_terminated') {
        dispatch({ type: 'session/ended' });
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
      offEvent();
      offStatus();
      transport.disconnect();
    };
  }, [dispatch, message, onPeerAudioRef, refreshSession, role, sessionId, transport]);
}
