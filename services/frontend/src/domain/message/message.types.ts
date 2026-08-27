export type MessageOrigin = 'self' | 'peer';

export type MessageState = 'pending' | 'sent' | 'failed';

export interface ChatMessage {
  id: string;
  origin: MessageOrigin;
  /** Already resolved for the customer's point of view — see message.mapper. */
  text: string;
  /** Present only for incoming messages that have synthesised speech. */
  audioUrl: string | null;
  sourceLanguage: string;
  targetLanguage: string;
  timestamp: string;
  state: MessageState;
}

export interface SendResult {
  messageId: string;
  originalText: string;
  translatedText: string;
  audioUrl: string | null;
  processingTimeMs: number;
}
