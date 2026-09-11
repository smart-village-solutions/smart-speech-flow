import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import type { ClientRole } from '@/core/roles';
import { resolveApiUrl } from '@/core/http/url';
import { historyToChatMessages } from './message.mapper';
import type { MessageHistoryDto } from './message.mapper';
import type { ChatMessage, SendResult } from './message.types';

interface SendTextInput {
  text: string;
  sourceLanguage: string;
  targetLanguage: string;
  role: ClientRole;
}

interface SendAudioInput {
  wav: Blob;
  sourceLanguage: string;
  targetLanguage: string;
  role: ClientRole;
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
  getHistory(sessionId: string, role: ClientRole): Promise<ChatMessage[]>;
  sendText(sessionId: string, input: SendTextInput): Promise<SendResult>;
  sendAudio(sessionId: string, input: SendAudioInput): Promise<SendResult>;
  /**
   * Puts a gateway audio path on the gateway origin. The authenticated clip
   * loader still uses the shared HTTP client after this resolution.
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
  const pathForRole = (role: ClientRole, sessionId: string) =>
    `/api/${role}/session/${sessionId}`;

  return {
    async getHistory(sessionId, role) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const response = await http.get<MessageHistoryDto>(
        `${pathForRole(role, safeId)}/messages`
      );
      return historyToChatMessages(response.data, resolveAudioUrl, role);
    },

    async sendText(sessionId, input) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const response = await http.post<SendResponseDto>(
        `${pathForRole(input.role, safeId)}/message`,
        {
          text: input.text,
          source_lang: input.sourceLanguage,
          target_lang: input.targetLanguage,
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

      const response = await http.post<SendResponseDto>(
        `${pathForRole(input.role, safeId)}/message`,
        form,
        { timeout: options.pipelineTimeoutMs }
      );
      return toSendResult(response.data);
    },

    resolveAudioUrl,
  };
}
