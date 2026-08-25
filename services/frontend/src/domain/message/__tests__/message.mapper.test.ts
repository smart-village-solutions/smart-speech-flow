import { describe, expect, it } from 'vitest';
import { historyToChatMessages, realtimeToChatMessage } from '@/domain/message/message.mapper';

/** Development, where the dev server proxies /api to the gateway. */
const sameOrigin = (url: string) => url;
/** Production, where the gateway is on its own host. */
const gatewayOrigin = (url: string) => `https://ssf.example${url}`;

describe('historyToChatMessages', () => {
  const dto = {
    session_id: 'A1B2C3D4',
    messages: [
      {
        id: 'm1',
        sender: 'customer' as const,
        original_text: 'I need a passport',
        translated_text: 'Ich brauche einen Reisepass',
        audio_base64: 'AAAA',
        source_lang: 'en',
        target_lang: 'de',
        timestamp: '2026-08-21T10:00:00+00:00',
      },
      {
        id: 'm2',
        sender: 'admin' as const,
        original_text: 'Haben Sie Ihren alten Pass dabei?',
        translated_text: 'Do you have your old passport with you?',
        audio_base64: 'BBBB',
        source_lang: 'de',
        target_lang: 'en',
        timestamp: '2026-08-21T10:00:05+00:00',
      },
    ],
  };

  it('shows the original text and no audio for the customer own message', () => {
    const [own] = historyToChatMessages(dto, sameOrigin);

    expect(own).toEqual({
      id: 'm1',
      origin: 'self',
      text: 'I need a passport',
      audioUrl: null,
      sourceLanguage: 'en',
      targetLanguage: 'de',
      timestamp: '2026-08-21T10:00:00+00:00',
      state: 'sent',
    });
  });

  it('shows the translated text and TTS audio for the agent message', () => {
    const [, incoming] = historyToChatMessages(dto, sameOrigin);

    expect(incoming).toEqual({
      id: 'm2',
      origin: 'peer',
      text: 'Do you have your old passport with you?',
      audioUrl: '/api/audio/m2.wav',
      sourceLanguage: 'de',
      targetLanguage: 'en',
      timestamp: '2026-08-21T10:00:05+00:00',
      state: 'sent',
    });
  });

  it('omits the audio URL when the agent message has no synthesised audio', () => {
    const [incoming] = historyToChatMessages(
      {
        session_id: 'A1B2C3D4',
        messages: [{ ...dto.messages[1], audio_base64: null }],
      },
      sameOrigin
    );

    expect(incoming.audioUrl).toBeNull();
  });

  // The deployed SPA and the gateway are on different hosts, so a relative
  // path is fetched from the SPA origin, where no audio exists.
  it('resolves history audio against the gateway origin', () => {
    const [, incoming] = historyToChatMessages(dto, gatewayOrigin);

    expect(incoming.audioUrl).toBe('https://ssf.example/api/audio/m2.wav');
  });
});

describe('realtimeToChatMessage', () => {
  const base = {
    type: 'message',
    message_id: 'm3',
    session_id: 'A1B2C3D4',
    source_lang: 'en',
    target_lang: 'de',
    sender: 'customer',
    timestamp: '2026-08-21T10:00:10+00:00',
  };

  it('maps a sender confirmation to a sent self message', () => {
    const message = realtimeToChatMessage(
      {
        ...base,
        role: 'sender_confirmation',
        text: 'my words',
        audio_available: false,
      },
      sameOrigin
    );

    expect(message).toEqual({
      id: 'm3',
      origin: 'self',
      text: 'my words',
      audioUrl: null,
      sourceLanguage: 'en',
      targetLanguage: 'de',
      timestamp: '2026-08-21T10:00:10+00:00',
      state: 'sent',
    });
  });

  it('maps a receiver message to a peer message carrying its audio URL', () => {
    const message = realtimeToChatMessage(
      {
        ...base,
        sender: 'admin',
        role: 'receiver_message',
        text: 'translated words',
        audio_available: true,
        audio_url: '/api/audio/m3.wav',
      },
      sameOrigin
    );

    expect(message?.origin).toBe('peer');
    expect(message?.audioUrl).toBe('/api/audio/m3.wav');
  });

  // The gateway sends a path, not a url; it is fetched by the browser as-is.
  it('resolves incoming audio against the gateway origin', () => {
    const message = realtimeToChatMessage(
      {
        ...base,
        sender: 'admin',
        role: 'receiver_message',
        text: 'translated words',
        audio_available: true,
        audio_url: '/api/audio/m3.wav',
      },
      gatewayOrigin
    );

    expect(message?.audioUrl).toBe('https://ssf.example/api/audio/m3.wav');
  });

  it('returns null for roles that are not messages', () => {
    expect(realtimeToChatMessage({ ...base, role: 'client_joined' }, sameOrigin)).toBeNull();
  });
});
