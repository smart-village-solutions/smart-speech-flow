import type { ChatMessage } from './message.types';

export interface MessageDto {
  id: string;
  sender: 'admin' | 'customer';
  original_text: string;
  translated_text: string;
  audio_base64: string | null;
  source_lang: string;
  target_lang: string;
  timestamp: string;
}

export interface MessageHistoryDto {
  session_id: string;
  messages: MessageDto[];
}

export interface RealtimePayload {
  role: string;
  message_id?: string;
  text?: string;
  source_lang?: string;
  target_lang?: string;
  sender?: string;
  timestamp?: string;
  audio_available?: boolean;
  audio_url?: string | null;
}

/** The gateway path a message's synthesised audio is served from. */
function audioUrlFor(messageId: string): string {
  return `/api/audio/${encodeURIComponent(messageId)}.wav`;
}

/**
 * Turns a gateway path into something the browser can fetch. Passed in rather
 * than read from config, so the mappers stay pure; see `resolveApiUrl`.
 */
export type ResolveAudioUrl = (url: string) => string;

/**
 * The gateway stores both halves of every message. The customer sees their own
 * words as spoken and the agent's words translated, so `sender` picks the half.
 */
export function historyToChatMessages(
  dto: MessageHistoryDto,
  resolveAudioUrl: ResolveAudioUrl
): ChatMessage[] {
  return dto.messages.map((message) => {
    const isOwn = message.sender === 'customer';

    return {
      id: message.id,
      origin: isOwn ? 'self' : 'peer',
      text: isOwn ? message.original_text : message.translated_text,
      audioUrl: !isOwn && message.audio_base64 ? resolveAudioUrl(audioUrlFor(message.id)) : null,
      sourceLanguage: message.source_lang,
      targetLanguage: message.target_lang,
      timestamp: message.timestamp,
      state: 'sent',
    };
  });
}

export function realtimeToChatMessage(
  payload: RealtimePayload,
  resolveAudioUrl: ResolveAudioUrl
): ChatMessage | null {
  if (payload.role !== 'sender_confirmation' && payload.role !== 'receiver_message') {
    return null;
  }

  const isOwn = payload.role === 'sender_confirmation';

  return {
    id: payload.message_id ?? '',
    origin: isOwn ? 'self' : 'peer',
    text: payload.text ?? '',
    audioUrl: isOwn || !payload.audio_url ? null : resolveAudioUrl(payload.audio_url),
    sourceLanguage: payload.source_lang ?? '',
    targetLanguage: payload.target_lang ?? '',
    timestamp: payload.timestamp ?? '',
    state: 'sent',
  };
}
