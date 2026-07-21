/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import WebSocketService from '../services/WebSocketService';
import type { WebSocketMessage, ClientType } from '../services/WebSocketService';

export interface Message {
  id: string;
  sender: 'admin' | 'customer';
  content_type: 'text' | 'audio';
  content?: string;
  audio_url?: string;
  translation?: string;
  translation_audio_url?: string;
  recognized_text?: string;
  timestamp: string;
  status?: 'sending' | 'sent' | 'error';
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

interface SessionContextType {
  sessionId: string | null;
  clientType: ClientType | null;
  messages: Message[];
  isActive: boolean;
  customerLanguage: string | null;
  adminLanguage: string;
  startSession: (sessionId: string, clientType: ClientType, customerLanguage?: string) => void;
  endSession: () => void;
  addMessage: (message: Message) => void;
  updateMessage: (messageId: string, updates: Partial<Message>) => void;
  registerTempId: (tempId: string, realId: string) => void;
}

const SessionContext = createContext<SessionContextType | null>(null);

function findTemporaryMessageId(tempIdMap: Map<string, string>, messageId: string) {
  for (const [tempId, realId] of tempIdMap) {
    if (realId === messageId) {
      return tempId;
    }
  }
  return null;
}

function confirmTemporaryMessage(
  messages: Message[],
  tempId: string,
  wsMessage: WebSocketMessage
): Message[] {
  if (!messages.some((message) => message.id === tempId)) {
    console.warn('Temporary message not found');
    return messages;
  }

  return messages.map<Message>((message) =>
    message.id === tempId
      ? {
          ...message,
          status: 'sent',
          content: wsMessage.text,
          pipeline_metadata: wsMessage.pipeline_metadata,
          audio_url: wsMessage.audio_url,
        }
      : message
  );
}

export function SessionProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [clientType, setClientType] = useState<ClientType | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isActive, setIsActive] = useState(false);
  const [customerLanguage, setCustomerLanguage] = useState<string | null>(null);
  const [adminLanguage] = useState<string>('de');
  const tempIdMapRef = useRef<Map<string, string>>(new Map());
  const pendingMessagesRef = useRef<Map<string, WebSocketMessage>>(new Map());

  const resetSessionState = useCallback(() => {
    tempIdMapRef.current.clear();
    pendingMessagesRef.current.clear();
    setMessages([]);
    setCustomerLanguage(null);
  }, []);

  const endSession = useCallback(() => {
    WebSocketService.disconnect();
    setSessionId(null);
    setClientType(null);
    setIsActive(false);
    resetSessionState();
  }, [resetSessionState]);

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => {
      const exists = prev.some((currentMessage) => currentMessage.id === message.id);
      if (exists) {
        console.warn('Message already exists, skipping');
        return prev;
      }
      return [...prev, message];
    });
  }, []);

  const updateMessage = useCallback((messageId: string, updates: Partial<Message>) => {
    setMessages((prev) =>
      prev.map((message) => (message.id === messageId ? { ...message, ...updates } : message))
    );
  }, []);

  const handleSessionActivated = useCallback((wsMessage: WebSocketMessage) => {
    if (wsMessage.customer_language) {
      setCustomerLanguage(wsMessage.customer_language);
    }
    if (wsMessage.role === 'session_activated' || wsMessage.client_type === 'customer') {
      setIsActive(true);
    }
  }, []);

  const handleReceiverMessage = useCallback((
    wsMessage: WebSocketMessage,
    activeClientType: ClientType | null
  ) => {
    const messageId = wsMessage.message_id;
    if (!messageId) {
      console.error('❌ receiver_message without message_id');
      return;
    }

    setMessages((currentMessages) => {
      const existingMessage = currentMessages.some((message) => message.id === messageId);
      if (existingMessage) {
        console.log('Receiver message already exists, skipping');
        return currentMessages;
      }

      return [
        ...currentMessages,
        {
          id: messageId,
          sender: activeClientType === 'admin' ? 'customer' : 'admin',
          content_type: wsMessage.audio_url ? 'audio' : 'text',
          content: wsMessage.text,
          translation_audio_url: wsMessage.audio_url,
          timestamp: new Date().toISOString(),
          status: 'sent',
          pipeline_metadata: wsMessage.pipeline_metadata,
        },
      ];
    });
  }, []);

  const handleSenderConfirmation = useCallback((wsMessage: WebSocketMessage) => {
    const messageId = wsMessage.message_id;
    if (!messageId) {
      return;
    }

    const tempId = findTemporaryMessageId(tempIdMapRef.current, messageId);

    if (tempId) {
      setTimeout(() => {
        setMessages((currentMessages) => confirmTemporaryMessage(currentMessages, tempId, wsMessage));
      }, 100);
      return;
    }

    pendingMessagesRef.current.set(messageId, wsMessage);
    setTimeout(() => {
      const stillPending = pendingMessagesRef.current.get(messageId);
      if (!stillPending) {
        return;
      }

      pendingMessagesRef.current.delete(messageId);
      addMessage({
        id: messageId,
        sender: clientType || 'admin',
        content_type: wsMessage.audio_url ? 'audio' : 'text',
        content: wsMessage.text,
        audio_url: wsMessage.audio_url,
        timestamp: new Date().toISOString(),
        status: 'sent',
        pipeline_metadata: wsMessage.pipeline_metadata,
      });
    }, 500);
  }, [addMessage, clientType]);

  const handleWebSocketMessage = useCallback((wsMessage: WebSocketMessage) => {
    if (wsMessage.role === 'session_terminated') {
      endSession();
      return;
    }

    if (wsMessage.role === 'session_activated' || wsMessage.role === 'client_joined') {
      handleSessionActivated(wsMessage);
      return;
    }

    if (wsMessage.role === 'sender_confirmation') {
      handleSenderConfirmation(wsMessage);
      return;
    }

    if (wsMessage.role === 'receiver_message') {
      handleReceiverMessage(wsMessage, clientType);
    }
  }, [clientType, endSession, handleReceiverMessage, handleSenderConfirmation, handleSessionActivated]);

  useEffect(() => {
    if (!sessionId || !clientType) {
      return;
    }

    WebSocketService.connect(sessionId, clientType);
    const unsubscribe = WebSocketService.onMessage(handleWebSocketMessage);

    return () => {
      unsubscribe();
      WebSocketService.disconnect();
    };
  }, [clientType, handleWebSocketMessage, sessionId]);

  const startSession = useCallback(
    (newSessionId: string, newClientType: ClientType, newCustomerLanguage?: string) => {
      const sessionChanged = sessionId !== newSessionId || clientType !== newClientType;

      if (sessionChanged) {
        WebSocketService.disconnect();
        resetSessionState();
      }

      setSessionId(newSessionId);
      setClientType(newClientType);
      setIsActive(true);
      if (newCustomerLanguage) {
        setCustomerLanguage(newCustomerLanguage);
      }
      if (!newCustomerLanguage && sessionChanged) {
        setCustomerLanguage(null);
      }
    },
    [clientType, resetSessionState, sessionId]
  );

  const registerTempId = useCallback((tempId: string, realId: string) => {
    tempIdMapRef.current.set(tempId, realId);

    const pendingMessage = pendingMessagesRef.current.get(realId);
    if (!pendingMessage) {
      return;
    }

    pendingMessagesRef.current.delete(realId);
    updateMessage(tempId, {
      status: 'sent',
      content: pendingMessage.text,
      pipeline_metadata: pendingMessage.pipeline_metadata,
      audio_url: pendingMessage.audio_url,
    });
  }, [updateMessage]);

  const contextValue = useMemo(
    () => ({
      sessionId,
      clientType,
      messages,
      isActive,
      customerLanguage,
      adminLanguage,
      startSession,
      endSession,
      addMessage,
      updateMessage,
      registerTempId,
    }),
    [
      sessionId,
      clientType,
      messages,
      isActive,
      customerLanguage,
      adminLanguage,
      startSession,
      endSession,
      addMessage,
      updateMessage,
      registerTempId,
    ]
  );

  return <SessionContext.Provider value={contextValue}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
}
