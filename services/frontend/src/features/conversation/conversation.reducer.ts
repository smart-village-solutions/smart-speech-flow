import type { RealtimeStatus } from '@/core/realtime/realtime.port';
import type { ChatMessage } from '@/domain/message/message.types';

export type ComposerMode = 'idle' | 'recording' | 'typing';

export interface ConversationState {
  messages: ChatMessage[];
  composer: ComposerMode;
  sending: boolean;
  connection: RealtimeStatus;
  /** Latches on the first successful connect, so the initial handshake is not
      reported to the customer as a reconnection. */
  hasConnected: boolean;
  ended: boolean;
  errorKey: string | null;
  /** True only while the error on show came from a send that can be repeated. */
  canRetry: boolean;
}

export type ConversationAction =
  | { type: 'history/loaded'; messages: ChatMessage[] }
  | { type: 'history/reloaded'; messages: ChatMessage[] }
  | { type: 'composer/mode'; mode: ComposerMode }
  | {
      type: 'send/started';
      tempId: string;
      /** Empty for a recording, whose transcript does not exist yet. */
      text: string;
      sourceLanguage: string;
      targetLanguage: string;
    }
  | { type: 'send/confirmed'; tempId: string; message: ChatMessage }
  | { type: 'send/failed'; tempId: string; errorKey: string }
  /** A failure with nothing to send again — a refused microphone, say. */
  | { type: 'error/raised'; errorKey: string }
  | { type: 'realtime/message'; message: ChatMessage }
  | { type: 'realtime/status'; status: RealtimeStatus }
  | { type: 'session/ended' }
  | { type: 'error/cleared' };

export const initialConversationState: ConversationState = {
  messages: [],
  composer: 'idle',
  sending: false,
  connection: 'disconnected',
  hasConnected: false,
  ended: false,
  errorKey: null,
  canRetry: false,
};

/**
 * A reconnect refetches, because a message broadcast while the socket was down
 * is never resent by the gateway. Anything still in flight locally has no
 * server copy yet and must survive the merge.
 */
function mergeReloadedHistory(state: ConversationState, loaded: ChatMessage[]): ChatMessage[] {
  const confirmed = new Set(loaded.map((message) => message.id));

  const inFlight = state.messages.filter(
    (message) =>
      (message.state === 'pending' || message.state === 'failed') && !confirmed.has(message.id)
  );

  return [...loaded, ...inFlight];
}

/**
 * The REST response and the WebSocket confirmation describe the same message,
 * so whichever lands second must not duplicate it.
 *
 * An id check alone only catches the response-first order. The gateway
 * broadcasts before that response returns, so the confirmation can overtake it,
 * and the copy it would clash with is still filed under a temp id. One send is
 * in flight at a time, so a self message arriving now IS the pending one: adopt
 * it rather than add a second bubble.
 */
function withRealtimeMessage(state: ConversationState, arrived: ChatMessage): ChatMessage[] | null {
  if (state.messages.some((message) => message.id === arrived.id)) {
    return null;
  }

  if (arrived.origin !== 'self') {
    return [...state.messages, arrived];
  }

  const inFlight = state.messages.findIndex(
    (message) => message.origin === 'self' && message.state === 'pending'
  );

  if (inFlight === -1) {
    return [...state.messages, arrived];
  }

  return state.messages.map((message, index) => (index === inFlight ? arrived : message));
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction
): ConversationState {
  switch (action.type) {
    case 'history/loaded':
      return { ...state, messages: action.messages };

    case 'history/reloaded':
      return { ...state, messages: mergeReloadedHistory(state, action.messages) };

    case 'composer/mode':
      // A finished session, or a send in flight, keeps the composer shut.
      if (state.ended || (state.sending && action.mode !== 'idle')) {
        return { ...state, composer: 'idle' };
      }
      return { ...state, composer: action.mode };

    case 'send/started': {
      if (state.sending || state.ended) {
        return state;
      }

      // Typing dots cover both kinds while the send is in flight. The words are
      // kept all the same, so a text message that fails still shows what it was.
      const placeholder: ChatMessage = {
        id: action.tempId,
        origin: 'self',
        text: action.text,
        audioUrl: null,
        sourceLanguage: action.sourceLanguage,
        targetLanguage: action.targetLanguage,
        timestamp: new Date().toISOString(),
        state: 'pending',
      };

      return {
        ...state,
        messages: [...state.messages, placeholder],
        composer: 'idle',
        sending: true,
        errorKey: null,
        canRetry: false,
      };
    }

    case 'send/confirmed':
      return {
        ...state,
        sending: false,
        messages: state.messages.map((message) =>
          message.id === action.tempId ? action.message : message
        ),
      };

    case 'send/failed':
      return {
        ...state,
        sending: false,
        errorKey: action.errorKey,
        canRetry: true,
        messages: state.messages.map((message) =>
          message.id === action.tempId ? { ...message, state: 'failed' } : message
        ),
      };

    case 'realtime/message': {
      const messages = withRealtimeMessage(state, action.message);
      return messages === null ? state : { ...state, messages };
    }

    case 'realtime/status':
      return {
        ...state,
        connection: action.status,
        hasConnected: state.hasConnected || action.status === 'connected',
      };

    case 'session/ended':
      return { ...state, ended: true, composer: 'idle' };

    case 'error/raised':
      return { ...state, errorKey: action.errorKey, canRetry: false };

    case 'error/cleared':
      return { ...state, errorKey: null, canRetry: false };

    default:
      return state;
  }
}
