import { describe, expect, it } from 'vitest';
import {
  conversationReducer,
  initialConversationState,
} from '@/features/conversation/conversation.reducer';
import type { ChatMessage } from '@/domain/message/message.types';

const peerMessage: ChatMessage = {
  id: 'm2',
  origin: 'peer',
  text: 'incoming',
  audioUrl: '/api/audio/m2.wav',
  sourceLanguage: 'de',
  targetLanguage: 'en',
  timestamp: '2026-08-21T10:00:05+00:00',
  state: 'sent',
};

function afterSend() {
  return conversationReducer(initialConversationState, {
    type: 'send/started',
    tempId: 'temp-1',
    sourceLanguage: 'en',
    targetLanguage: 'de',
  });
}

describe('conversationReducer', () => {
  it('loads history', () => {
    const state = conversationReducer(initialConversationState, {
      type: 'history/loaded',
      messages: [peerMessage],
    });

    expect(state.messages).toEqual([peerMessage]);
  });

  it('adds a pending own message and closes the composer when a send starts', () => {
    const state = afterSend();

    expect(state.sending).toBe(true);
    expect(state.composer).toBe('idle');
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ id: 'temp-1', origin: 'self', state: 'pending' });
  });

  it('replaces the placeholder with the confirmed message', () => {
    const confirmed: ChatMessage = { ...peerMessage, id: 'm1', origin: 'self', text: 'my words' };
    const state = conversationReducer(afterSend(), {
      type: 'send/confirmed',
      tempId: 'temp-1',
      message: confirmed,
    });

    expect(state.sending).toBe(false);
    expect(state.messages).toEqual([confirmed]);
  });

  it('marks the placeholder failed and records the message key', () => {
    const state = conversationReducer(afterSend(), {
      type: 'send/failed',
      tempId: 'temp-1',
      errorKey: 'conversation.sendFailed',
    });

    expect(state.sending).toBe(false);
    expect(state.messages[0].state).toBe('failed');
    expect(state.errorKey).toBe('conversation.sendFailed');
  });

  it('appends realtime messages', () => {
    const state = conversationReducer(initialConversationState, {
      type: 'realtime/message',
      message: peerMessage,
    });

    expect(state.messages).toEqual([peerMessage]);
  });

  it('ignores a realtime message whose id is already present', () => {
    const once = conversationReducer(initialConversationState, {
      type: 'realtime/message',
      message: peerMessage,
    });
    const twice = conversationReducer(once, { type: 'realtime/message', message: peerMessage });

    expect(twice.messages).toHaveLength(1);
    expect(twice).toBe(once);
  });

  it('tracks the connection status', () => {
    const state = conversationReducer(initialConversationState, {
      type: 'realtime/status',
      status: 'connected',
    });

    expect(state.connection).toBe('connected');
  });

  it('ends the session and closes the composer', () => {
    const state = conversationReducer(
      conversationReducer(initialConversationState, { type: 'composer/mode', mode: 'typing' }),
      { type: 'session/ended' }
    );

    expect(state.ended).toBe(true);
    expect(state.composer).toBe('idle');
  });

  it('refuses to open the composer once the session has ended', () => {
    const ended = conversationReducer(initialConversationState, { type: 'session/ended' });
    const state = conversationReducer(ended, { type: 'composer/mode', mode: 'recording' });

    expect(state.composer).toBe('idle');
  });

  it('refuses to start a second send while one is in flight', () => {
    const state = conversationReducer(afterSend(), {
      type: 'send/started',
      tempId: 'temp-2',
      sourceLanguage: 'en',
      targetLanguage: 'de',
    });

    expect(state.messages).toHaveLength(1);
  });

  it('clears the error', () => {
    const failed = conversationReducer(afterSend(), {
      type: 'send/failed',
      tempId: 'temp-1',
      errorKey: 'conversation.sendFailed',
    });

    expect(conversationReducer(failed, { type: 'error/cleared' }).errorKey).toBeNull();
  });

  describe('history/reloaded', () => {
    const server = (id: string, text: string) => ({
      id,
      origin: 'peer' as const,
      text,
      audioUrl: null,
      sourceLanguage: 'de',
      targetLanguage: 'en',
      timestamp: '2026-08-24T10:00:00+00:00',
      state: 'sent' as const,
    });

    it('picks up a message that was missed while the socket was down', () => {
      const state = conversationReducer(initialConversationState, {
        type: 'history/loaded',
        messages: [server('m1', 'first')],
      });

      const next = conversationReducer(state, {
        type: 'history/reloaded',
        messages: [server('m1', 'first'), server('m2', 'missed while offline')],
      });

      expect(next.messages.map((message) => message.id)).toEqual(['m1', 'm2']);
    });

    it('keeps a send that is still in flight', () => {
      const withPending = conversationReducer(initialConversationState, {
        type: 'send/started',
        tempId: 'temp-1',
        sourceLanguage: 'en',
        targetLanguage: 'de',
      });

      const next = conversationReducer(withPending, {
        type: 'history/reloaded',
        messages: [server('m1', 'first')],
      });

      expect(next.messages.map((message) => message.id)).toEqual(['m1', 'temp-1']);
      expect(next.messages[1].state).toBe('pending');
    });

    it('keeps a failed send so its retry control survives', () => {
      const failed = conversationReducer(
        conversationReducer(initialConversationState, {
          type: 'send/started',
          tempId: 'temp-1',
          sourceLanguage: 'en',
          targetLanguage: 'de',
        }),
        { type: 'send/failed', tempId: 'temp-1', errorKey: 'conversation.sendFailed' }
      );

      const next = conversationReducer(failed, {
        type: 'history/reloaded',
        messages: [server('m1', 'first')],
      });

      expect(next.messages.map((message) => message.id)).toEqual(['m1', 'temp-1']);
    });

    it('drops a local copy the server has since confirmed', () => {
      const withPending = conversationReducer(initialConversationState, {
        type: 'send/started',
        tempId: 'temp-1',
        sourceLanguage: 'en',
        targetLanguage: 'de',
      });

      const next = conversationReducer(withPending, {
        type: 'history/reloaded',
        messages: [{ ...server('temp-1', 'mine'), origin: 'self' }],
      });

      expect(next.messages).toHaveLength(1);
      expect(next.messages[0].state).toBe('sent');
    });
  });

  describe('a send confirmed over both channels at once', () => {
    const confirmation = {
      id: 'm7',
      origin: 'self' as const,
      text: 'hello',
      audioUrl: null,
      sourceLanguage: 'en',
      targetLanguage: 'de',
      timestamp: '2026-08-24T10:00:00+00:00',
      state: 'sent' as const,
    };

    const sending = () =>
      conversationReducer(initialConversationState, {
        type: 'send/started',
        tempId: 'temp-1',
        sourceLanguage: 'en',
        targetLanguage: 'de',
      });

    // The gateway broadcasts before the REST call returns, so the socket
    // confirmation can overtake the response. The in-flight copy is still
    // filed under its temp id, so an id check alone does not see the clash.
    it('shows one message when the socket confirmation arrives first', () => {
      const overtaken = conversationReducer(sending(), {
        type: 'realtime/message',
        message: confirmation,
      });

      const settled = conversationReducer(overtaken, {
        type: 'send/confirmed',
        tempId: 'temp-1',
        message: confirmation,
      });

      expect(settled.messages).toHaveLength(1);
      expect(settled.messages[0].id).toBe('m7');
      expect(settled.messages[0].state).toBe('sent');
      expect(settled.sending).toBe(false);
    });

    it('shows one message when the response arrives first', () => {
      const settled = conversationReducer(sending(), {
        type: 'send/confirmed',
        tempId: 'temp-1',
        message: confirmation,
      });

      const afterSocket = conversationReducer(settled, {
        type: 'realtime/message',
        message: confirmation,
      });

      expect(afterSocket.messages).toHaveLength(1);
      expect(afterSocket.messages[0].id).toBe('m7');
    });

    it('leaves no two messages sharing an id, whatever the order', () => {
      const overtaken = conversationReducer(sending(), {
        type: 'realtime/message',
        message: confirmation,
      });
      const settled = conversationReducer(overtaken, {
        type: 'send/confirmed',
        tempId: 'temp-1',
        message: confirmation,
      });

      const ids = settled.messages.map((message) => message.id);
      expect(new Set(ids).size).toBe(ids.length);
    });

    it('still appends an incoming message that arrives mid-send', () => {
      const peer = { ...confirmation, id: 'm8', origin: 'peer' as const, text: 'from the agent' };

      const next = conversationReducer(sending(), { type: 'realtime/message', message: peer });

      expect(next.messages.map((message) => message.id)).toEqual(['temp-1', 'm8']);
      expect(next.messages[0].state).toBe('pending');
    });

    it('appends a self message when nothing of ours is in flight', () => {
      const next = conversationReducer(initialConversationState, {
        type: 'realtime/message',
        message: confirmation,
      });

      expect(next.messages.map((message) => message.id)).toEqual(['m7']);
    });
  });

  describe('hasConnected', () => {
    it('starts false, so a first connect is not mistaken for a reconnect', () => {
      expect(initialConversationState.hasConnected).toBe(false);
    });

    it('stays false while the first connection is still being made', () => {
      const connecting = conversationReducer(initialConversationState, {
        type: 'realtime/status',
        status: 'connecting',
      });

      expect(connecting.hasConnected).toBe(false);
    });

    it('latches once a connection has been made', () => {
      const connected = conversationReducer(initialConversationState, {
        type: 'realtime/status',
        status: 'connected',
      });
      const dropped = conversationReducer(connected, {
        type: 'realtime/status',
        status: 'disconnected',
      });

      expect(connected.hasConnected).toBe(true);
      expect(dropped.hasConnected).toBe(true);
      expect(dropped.connection).toBe('disconnected');
    });
  });
});
