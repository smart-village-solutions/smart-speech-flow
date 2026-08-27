import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import { resolveApiUrl } from '@/core/http/url';
import { historyToChatMessages } from './message.mapper';
import type { MessageHistoryDto } from './message.mapper';
import type { ChatMessage, SendResult } from './message.types';

interface SendTextInput {
  text: string;
  sourceLanguage: string;
  targetLanguage: string;
}

interface SendAudioInput {
  wav: Blob;
  sourceLanguage: string;
  targetLanguage: string;
}

interface SendResponseDto {
  status: string;
  message_id: string;
  session_id: string;
  original_text: string;
  translated_text: string;
  audio_available: boolean;
  audio_url: string | null;
  processing_time_ms: number;
  pipeline_type: string;
}

export interface MessageRepository {
  getHistory(sessionId: string): Promise<ChatMessage[]>;
  sendText(sessionId: string, input: SendTextInput): Promise<SendResult>;
  sendAudio(sessionId: string, input: SendAudioInput): Promise<SendResult>;
  /**
   * Puts a gateway audio path on the gateway origin. Exposed because the
   * socket delivers its own paths, which the screen has to resolve the same
   * way the history does.
   */
  resolveAudioUrl(url: string): string;
}

function toSendResult(dto: SendResponseDto): SendResult {
  return {
    messageId: dto.message_id,
    originalText: dto.original_text,
    translatedText: dto.translated_text,
    audioUrl: dto.audio_available ? dto.audio_url : null,
    processingTimeMs: dto.processing_time_ms,
  };
}

export function createMessageRepository(
  http: AxiosInstance,
  options: { pipelineTimeoutMs: number; apiBaseUrl: string }
): MessageRepository {
  const resolveAudioUrl = (url: string) => resolveApiUrl(options.apiBaseUrl, url);

  return {
    async getHistory(sessionId) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const response = await http.get<MessageHistoryDto>(`/api/session/${safeId}/messages`);
      return historyToChatMessages(response.data, resolveAudioUrl);
    },

    async sendText(sessionId, input) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const response = await http.post<SendResponseDto>(
        `/api/session/${safeId}/message`,
        {
          text: input.text,
          source_lang: input.sourceLanguage,
          target_lang: input.targetLanguage,
          client_type: 'customer',
        },
        { timeout: options.pipelineTimeoutMs }
      );
      return toSendResult(response.data);
    },

    async sendAudio(sessionId, input) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const form = new FormData();
      form.append('file', input.wav, 'recording.wav');
      form.append('source_lang', input.sourceLanguage);
      form.append('target_lang', input.targetLanguage);
      form.append('client_type', 'customer');

      const response = await http.post<SendResponseDto>(`/api/session/${safeId}/message`, form, {
        timeout: options.pipelineTimeoutMs,
      });
      return toSendResult(response.data);
    },

    resolveAudioUrl,
  };
}
