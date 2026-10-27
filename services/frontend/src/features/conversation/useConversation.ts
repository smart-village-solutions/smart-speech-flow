import { useCallback, useEffect, useReducer, useRef } from 'react';
import { useServices } from '@/app/providers/services';
import type { ClientRole } from '@/core/roles';
import { AppError, isSessionGone } from '@/core/http/AppError';
import { randomId } from '@/core/ids';
import type { ChatMessage } from '@/domain/message/message.types';
import {
  conversationReducer,
  initialConversationState,
  type ConversationAction,
  type ConversationState,
} from './conversation.reducer';
import { useConversationFeed } from './useConversationFeed';
import { useLatestRef } from './useLatestRef';
import { useSessionRefresh } from './useSessionRefresh';

interface UseConversationOptions {
  /** Which end of the session this screen is. Never defaulted. */
  role: ClientRole;
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
  options: UseConversationOptions
): UseConversationResult {
  const { message } = useServices();
  const { role } = options;
  const [state, dispatch] = useReducer(conversationReducer, initialConversationState);
  const refreshSession = useSessionRefresh(sessionId);

  // Held in a ref so a new callback identity does not tear down the socket.
  const onPeerAudioRef = useRef(options.onPeerAudio);
  // A retry sends the languages current when it runs: after a guest language
  // switch, the pair captured at the first attempt would fail forever.
  const languagesRef = useRef(languages);
  // A recording is handed over after it stops, which can be after the end.
  const endedRef = useRef(state.ended);

  useEffect(() => {
    onPeerAudioRef.current = options.onPeerAudio;
    languagesRef.current = languages;
    endedRef.current = state.ended;
  });

  const recordingVersionRef = useLatestRef(state.recording.status.stateVersion);
  useConversationFeed({ sessionId, role, dispatch, onPeerAudioRef, recordingVersionRef });

  const send = useCallback(
    async (perform: () => Promise<{ messageId: string; originalText: string }>, text: string) => {
      if (endedRef.current) {
        return;
      }
      const tempId = `temp-${randomId()}`;
      const { source, target } = languagesRef.current;
      dispatch({
        type: 'send/started',
        tempId,
        text,
        sourceLanguage: source,
        targetLanguage: target,
      });

      try {
        const result = await perform();
        const confirmed: ChatMessage = {
          id: result.messageId,
          origin: 'self',
          text: result.originalText,
          audioUrl: null,
          sourceLanguage: source,
          targetLanguage: target,
          timestamp: new Date().toISOString(),
          state: 'sent',
        };
        dispatch({ type: 'send/confirmed', tempId, message: confirmed });
      } catch (error) {
        if (error instanceof AppError && error.kind === 'languageChanged') {
          refreshSession();
        }
        const errorKey =
          error instanceof AppError ? error.userMessageKey : 'conversation.sendFailed';
        dispatch({ type: 'send/failed', tempId, errorKey });
        if (isSessionGone(error)) {
          dispatch({ type: 'session/ended' });
        }
      }
    },
    [refreshSession]
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
              sourceLanguage: languagesRef.current.source,
              targetLanguage: languagesRef.current.target,
              role,
            }),
          text
        );
      lastAttempt.current = attempt;
      return attempt();
    },
    [message, role, send, sessionId]
  );

  const sendAudio = useCallback(
    (wav: Blob) => {
      const attempt = () =>
        send(
          () =>
            message.sendAudio(sessionId, {
              wav,
              sourceLanguage: languagesRef.current.source,
              targetLanguage: languagesRef.current.target,
              role,
            }),
          // A recording has no transcript until the gateway returns one.
          ''
        );
      lastAttempt.current = attempt;
      return attempt();
    },
    [message, role, send, sessionId]
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
