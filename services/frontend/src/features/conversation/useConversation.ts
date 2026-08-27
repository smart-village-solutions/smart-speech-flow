import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { randomId } from '@/core/ids';
import { realtimeToChatMessage } from '@/domain/message/message.mapper';
import type { ChatMessage } from '@/domain/message/message.types';
import {
  conversationReducer,
  initialConversationState,
  type ConversationAction,
  type ConversationState,
} from './conversation.reducer';

const HEARTBEAT_MS = 30_000;

interface UseConversationOptions {
  /**
   * Fired for a peer message that arrives over the wire carrying audio — the
   * autoplay hook. History never routes through here, which is what keeps old
   * messages silent on page load.
   */
  onPeerAudio?: (id: string, url: string) => void;
}

interface UseConversationResult {
  state: ConversationState;
  dispatch: (action: ConversationAction) => void;
  sendText: (text: string) => Promise<void>;
  sendAudio: (wav: Blob) => Promise<void>;
  /** Non-null only while a send has failed and can be attempted again. */
  retryLast: (() => void) | null;
}

export function useConversation(
  sessionId: string,
  languages: { source: string; target: string },
  options: UseConversationOptions = {}
): UseConversationResult {
  const { message, session, createRealtime } = useServices();
  const [state, dispatch] = useReducer(conversationReducer, initialConversationState);
  const transport = useMemo(() => createRealtime(), [createRealtime]);

  // Held in a ref so a new callback identity does not tear down the socket.
  const onPeerAudioRef = useRef(options.onPeerAudio);

  useEffect(() => {
    onPeerAudioRef.current = options.onPeerAudio;
  });

  useEffect(() => {
    let cancelled = false;

    void message
      .getHistory(sessionId)
      .then((messages) => {
        if (!cancelled) {
          dispatch({ type: 'history/loaded', messages });
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [message, sessionId]);

  useEffect(() => {
    const offEvent = transport.onEvent((event) => {
      if (event.role === 'session_terminated') {
        dispatch({ type: 'session/ended' });
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
          .getHistory(sessionId)
          .then((messages) => dispatch({ type: 'history/reloaded', messages }))
          .catch(() => undefined);
      }

      seenConnected = true;
    });

    transport.connect(sessionId);

    return () => {
      offEvent();
      offStatus();
      transport.disconnect();
    };
  }, [message, sessionId, transport]);

  useEffect(() => {
    const beat = setInterval(
      () => void session.reportActivity(sessionId).catch(() => undefined),
      HEARTBEAT_MS
    );
    return () => clearInterval(beat);
  }, [session, sessionId]);

  const send = useCallback(
    async (
      perform: () => Promise<{ messageId: string; originalText: string }>,
      text: string
    ) => {
      const tempId = `temp-${randomId()}`;
      dispatch({
        type: 'send/started',
        tempId,
        text,
        sourceLanguage: languages.source,
        targetLanguage: languages.target,
      });

      try {
        const result = await perform();
        const confirmed: ChatMessage = {
          id: result.messageId,
          origin: 'self',
          text: result.originalText,
          audioUrl: null,
          sourceLanguage: languages.source,
          targetLanguage: languages.target,
          timestamp: new Date().toISOString(),
          state: 'sent',
        };
        dispatch({ type: 'send/confirmed', tempId, message: confirmed });
      } catch (error) {
        const errorKey =
          error instanceof AppError ? error.userMessageKey : 'conversation.sendFailed';
        dispatch({ type: 'send/failed', tempId, errorKey });
      }
    },
    [languages.source, languages.target]
  );

  const lastAttempt = useRef<(() => Promise<void>) | null>(null);
  const retry = useCallback(() => void lastAttempt.current?.(), []);

  const sendText = useCallback(
    (text: string) => {
      const attempt = () =>
        send(
          () =>
            message.sendText(sessionId, {
              text,
              sourceLanguage: languages.source,
              targetLanguage: languages.target,
            }),
          text
        );
      lastAttempt.current = attempt;
      return attempt();
    },
    [languages.source, languages.target, message, send, sessionId]
  );

  const sendAudio = useCallback(
    (wav: Blob) => {
      const attempt = () =>
        send(
          () =>
            message.sendAudio(sessionId, {
              wav,
              sourceLanguage: languages.source,
              targetLanguage: languages.target,
            }),
          // A recording has no transcript until the gateway returns one.
          ''
        );
      lastAttempt.current = attempt;
      return attempt();
    },
    [languages.source, languages.target, message, send, sessionId]
  );

  return {
    state,
    dispatch,
    sendText,
    sendAudio,
    // Each send path remembers its own payload, so one control retries either.
    // Gated on the send having failed, not merely on an error being on show: a
    // refused microphone leaves the last attempt untouched, and offering it
    // there would send the previous message a second time.
    retryLast: state.canRetry ? retry : null,
  };
}
