import api from './api';

export interface Message {
  id: string;
  sender: 'admin' | 'customer';
  content_type: 'text' | 'audio';
  content?: string;
  audio_url?: string;
  translation?: string;
  translation_audio_url?: string;
  timestamp: string;
  pipeline_metadata?: {
    input?: {
      type: 'audio' | 'text';
      source_lang: string;
      audio_url?: string;
    };
    steps?: Array<{
      name: string;
      input?: unknown;
      output?: unknown;
      started_at?: string;
      completed_at?: string;
      duration_ms: number;
    }>;
    total_duration_ms?: number;
    pipeline_started_at?: string;
    pipeline_completed_at?: string;
  };
}

export interface SendMessageRequest {
  text?: string;
  source_lang: string;
  target_lang: string;
  client_type: 'admin' | 'customer';
}

export interface SendMessageResponse {
  message_id: string;
  status: string;
  message: string;
}

export interface GetMessagesResponse {
  messages: Message[];
  session_id: string;
}

class MessageService {
  /**
   * Send a message (text or audio)
   * POST /api/session/{sessionId}/message
   */
  async sendMessage(sessionId: string, data: SendMessageRequest): Promise<SendMessageResponse> {
    const response = await api.post<SendMessageResponse>(`/api/session/${sessionId}/message`, data);
    return response.data;
  }

  /**
   * Get message history for a session
   * GET /api/session/{sessionId}/messages
   */
  async getMessages(sessionId: string): Promise<Message[]> {
    const response = await api.get<GetMessagesResponse>(`/api/session/${sessionId}/messages`);
    return response.data.messages || [];
  }
}

export default new MessageService();
