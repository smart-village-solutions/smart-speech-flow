import { useEffect, useMemo, type Dispatch, type RefObject } from 'react';
import { useServices } from '@/app/providers/services';
import { isSessionGone } from '@/core/http/AppError';
import type { ClientRole } from '@/core/roles';
import type { RealtimeEvent } from '@/core/realtime/realtime.port';
import { realtimeToChatMessage } from '@/domain/message/message.mapper';
import { recordingEvents } from '@/features/recording/recordingEvents';
import type { ConversationAction } from './conversation.reducer';
import { useSessionRefresh } from './useSessionRefresh';

interface ConversationFeedOptions {
  sessionId: string;
  role: ClientRole;
  dispatch: Dispatch<ConversationAction>;
  /** The autoplay hook, read through a ref so a new callback keeps the socket. */
  onPeerAudioRef: RefObject<((id: string, url: string) => void) | undefined>;
  /** The recording state version on screen, so older frames are not acknowledged. */
  recordingVersionRef: RefObject<number>;
}

/** What arrives without being asked for: the history, then the gateway's pushes. */
export function useConversationFeed({
  sessionId,
  role,
  dispatch,
  onPeerAudioRef,
  recordingVersionRef,
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
      .catch((error: unknown) => {
        if (!cancelled && isSessionGone(error)) {
          dispatch({ type: 'session/ended' });
          transport.disconnect();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [dispatch, message, role, sessionId, transport]);

  useEffect(() => {
    const warning = createTimeoutWarning(dispatch);

    const end = () => {
      dispatch({ type: 'session/ended' });
      // The gateway closes the socket next; reconnecting to an ended session only fails.
      transport.disconnect();
    };

    // The idle timeout runs only while no admin is connected, so an admin
    // joining lifts it. Were the warning for the session's absolute limit
    // instead, the gateway repeats it within a minute of the admin connecting.
    const onJoined = (event: RealtimeEvent) => {
      if (event.client_type === 'admin') {
        warning.withdraw();
      }
    };

    const sessionEvents = new Map<string, (event: RealtimeEvent) => void>([
      ['session_terminated', end],
      ['timeout_warning', (event) => warning.show(event)],
      ['client_joined', onJoined],
      ['customer_language_changed', refreshSession],
      ...recordingEvents(dispatch, transport, () => recordingVersionRef.current),
    ]);

    const offEvent = transport.onEvent((event) => {
      const handle = sessionEvents.get(event.role);
      if (handle !== undefined) {
        handle(event);
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
    // effect above has already loaded that history. The end frame is lost the
    // same way, and the refetch is where a session gone meanwhile shows.
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
          .catch((error: unknown) => {
            if (isSessionGone(error)) {
              end();
            }
          });
      }

      seenConnected = true;
    });

    void transport.connect(sessionId, role);

    return () => {
      warning.dispose();
      offEvent();
      offStatus();
      transport.disconnect();
    };
  }, [
    dispatch,
    message,
    onPeerAudioRef,
    recordingVersionRef,
    refreshSession,
    role,
    sessionId,
    transport,
  ]);
}

/** The idle-timeout warning on show, taken down at the time it names. */
function createTimeoutWarning(dispatch: Dispatch<ConversationAction>) {
  let expiry: ReturnType<typeof setTimeout> | undefined;

  return {
    show(event: RealtimeEvent) {
      const endsAt = warningEndsAt(event);
      dispatch({ type: 'session/timeoutWarning', endsAt });
      clearTimeout(expiry);
      expiry = setTimeout(
        () => dispatch({ type: 'session/timeoutWarningWithdrawn' }),
        Math.max(0, endsAt - Date.now())
      );
    },
    withdraw() {
      clearTimeout(expiry);
      dispatch({ type: 'session/timeoutWarningWithdrawn' });
    },
    dispose() {
      clearTimeout(expiry);
    },
  };
}

const DEFAULT_WARNING_MINUTES = 5;

/** The gateway's deadline; a gateway from before it was sent gives only the minutes left. */
function warningEndsAt(event: RealtimeEvent): number {
  const stated = typeof event.timeout_at === 'string' ? Date.parse(event.timeout_at) : Number.NaN;
  if (Number.isFinite(stated)) {
    return stated;
  }
  const minutes = event.remaining_minutes;
  const valid = typeof minutes === 'number' && Number.isFinite(minutes) && minutes > 0;
  return Date.now() + (valid ? minutes : DEFAULT_WARNING_MINUTES) * 60_000;
}
