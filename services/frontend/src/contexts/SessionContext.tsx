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
    console.log('🔵 addMessage called:', message.id, message.content?.substring(0, 20));
    setMessages((prev) => {
      const exists = prev.find((currentMessage) => currentMessage.id === message.id);
      if (exists) {
        console.warn('⚠️ Message already exists, skipping:', message.id);
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
    console.log('Session activated/client joined:', wsMessage);
    if (wsMessage.customer_language) {
      console.log('✅ Setting customer language:', wsMessage.customer_language);
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

    console.log('📥 receiver_message received:', messageId);
    setMessages((currentMessages) => {
      const existingMessage = currentMessages.find((message) => message.id === messageId);
      if (existingMessage) {
        console.log('⚠️ receiver_message already exists, skipping:', messageId);
        return currentMessages;
      }

      console.log('✅ Creating new receiver message:', messageId);
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

    const tempIdMap = tempIdMapRef.current;
    console.log(
      '📤 sender_confirmation received:',
      messageId,
      'tempMap has:',
      Array.from(tempIdMap.entries())
    );

    const tempId =
      Array.from(tempIdMap.entries()).find(([, realId]) => realId === messageId)?.[0] ??
      null;

    if (tempId) {
      console.log('⏳ Found temp ID mapping:', tempId, '-> waiting for message');
      setTimeout(() => {
        const message = messages.find((currentMessage) => currentMessage.id === tempId);
        if (message) {
          console.log('✏️ Updating temp message:', tempId);
          updateMessage(tempId, {
            status: 'sent',
            content: wsMessage.text,
            pipeline_metadata: wsMessage.pipeline_metadata,
            audio_url: wsMessage.audio_url,
          });
        } else {
          console.warn('⚠️ Temp message not found yet:', tempId);
        }
      }, 100);
      return;
    }

    console.log('⏳ No mapping yet - storing pending message:', messageId);
    pendingMessagesRef.current.set(messageId, wsMessage);
    setTimeout(() => {
      const stillPending = pendingMessagesRef.current.get(messageId);
      if (!stillPending) {
        return;
      }

      console.log('⚠️ Timeout - creating message without mapping:', messageId);
      pendingMessagesRef.current.delete(messageId);
      const existingMessage = messages.find((message) => message.id === messageId);
      if (existingMessage) {
        return;
      }

      console.log('➕ Creating new sender_confirmation message:', messageId);
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
  }, [addMessage, clientType, messages, updateMessage]);

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
    console.log('🔗 registerTempId called:', tempId, '->', realId);
    tempIdMapRef.current.set(tempId, realId);

    const pendingMessage = pendingMessagesRef.current.get(realId);
    if (!pendingMessage) {
      return;
    }

    console.log('✅ Found pending message - processing now:', realId);
    pendingMessagesRef.current.delete(realId);
    console.log('✏️ Updating temp message with pending data:', tempId);
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
