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
}

export type ConversationAction =
  | { type: 'history/loaded'; messages: ChatMessage[] }
  | { type: 'history/reloaded'; messages: ChatMessage[] }
  | { type: 'composer/mode'; mode: ComposerMode }
  | { type: 'send/started'; tempId: string; sourceLanguage: string; targetLanguage: string }
  | { type: 'send/confirmed'; tempId: string; message: ChatMessage }
  | { type: 'send/failed'; tempId: string; errorKey: string }
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
};

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction
): ConversationState {
  switch (action.type) {
    case 'history/loaded':
      return { ...state, messages: action.messages };

    case 'history/reloaded': {
      // A reconnect refetches, because a message broadcast while the socket was
      // down is never resent by the gateway. Anything still in flight locally
      // has no server copy yet and must survive the merge.
      const confirmed = new Set(action.messages.map((message) => message.id));
      const inFlight = state.messages.filter(
        (message) =>
          (message.state === 'pending' || message.state === 'failed') &&
          !confirmed.has(message.id)
      );

      return { ...state, messages: [...action.messages, ...inFlight] };
    }

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

      // Placeholder text stays empty on purpose: for audio the transcript does
      // not exist yet, and the export renders typing dots for both kinds.
      const placeholder: ChatMessage = {
        id: action.tempId,
        origin: 'self',
        text: '',
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
        messages: state.messages.map((message) =>
          message.id === action.tempId ? { ...message, state: 'failed' } : message
        ),
      };

    case 'realtime/message': {
      // The REST response and the WebSocket confirmation describe the same
      // message, so whichever lands second must not duplicate it.
      if (state.messages.some((message) => message.id === action.message.id)) {
        return state;
      }

      // An id check alone only catches the response-first order. The gateway
      // broadcasts before that response returns, so the confirmation can
      // overtake it, and the copy it would clash with is still filed under a
      // temp id. One send is in flight at a time, so a self message arriving
      // now IS the pending one: adopt it rather than add a second bubble.
      if (action.message.origin === 'self') {
        const inFlight = state.messages.findIndex(
          (message) => message.origin === 'self' && message.state === 'pending'
        );

        if (inFlight !== -1) {
          return {
            ...state,
            messages: state.messages.map((message, index) =>
              index === inFlight ? action.message : message
            ),
          };
        }
      }

      return { ...state, messages: [...state.messages, action.message] };
    }

    case 'realtime/status':
      return {
        ...state,
        connection: action.status,
        hasConnected: state.hasConnected || action.status === 'connected',
      };

    case 'session/ended':
      return { ...state, ended: true, composer: 'idle' };

    case 'error/cleared':
      return { ...state, errorKey: null };

    default:
      return state;
  }
}
