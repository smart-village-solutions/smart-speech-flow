import { createContext, useContext, useState, useEffect, useRef } from 'react';
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
      input?: any;
      output?: any;
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

export function SessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [clientType, setClientType] = useState<ClientType | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isActive, setIsActive] = useState(false);
  const [customerLanguage, setCustomerLanguage] = useState<string | null>(null);
  const [adminLanguage] = useState<string>('de');
  // Map to track temporary message IDs to real IDs - use useRef to persist across renders
  const tempIdMapRef = useRef<Map<string, string>>(new Map());
  // Map to track pending messages that arrived before HTTP response
  const pendingMessagesRef = useRef<Map<string, WebSocketMessage>>(new Map());

  useEffect(() => {
    if (!sessionId || !clientType) return;

    // Connect to WebSocket
    WebSocketService.connect(sessionId, clientType);

    // Handle incoming messages
    const unsubscribe = WebSocketService.onMessage(handleWebSocketMessage);

    return () => {
      unsubscribe();
      WebSocketService.disconnect();
    };
  }, [sessionId, clientType]);

  const handleWebSocketMessage = (wsMessage: WebSocketMessage) => {
    if (wsMessage.role === 'session_terminated') {
      endSession();
      return;
    }

    if (wsMessage.role === 'session_activated') {
      // Customer has joined - admin can see this
      console.log('Session activated, customer joined with language:', wsMessage.customer_language);
      // Update customer language when customer joins
      if (wsMessage.customer_language) {
        setCustomerLanguage(wsMessage.customer_language);
      }
      // Set session as active
      setIsActive(true);
      return;
    }

    if (!wsMessage.message_id) return;

    if (wsMessage.role === 'sender_confirmation') {
      // This is confirmation of our own sent message
      const tempIdMap = tempIdMapRef.current;
      console.log('📤 sender_confirmation received:', wsMessage.message_id, 'tempMap has:', Array.from(tempIdMap.entries()));

      // First, check if we have a temp ID mapping
      let tempId: string | null = null;
      for (const [tId, realId] of tempIdMap.entries()) {
        if (realId === wsMessage.message_id) {
          tempId = tId;
          break;
        }
      }

      // If we have a temp ID, WAIT for the optimistic message to appear
      if (tempId) {
        console.log('⏳ Found temp ID mapping:', tempId, '-> waiting for message');
        // Use a small timeout to allow React state to settle
        setTimeout(() => {
          const msg = messages.find((m) => m.id === tempId);
          if (msg) {
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

      // Otherwise, store as pending and wait for HTTP response
      // At this point we know message_id exists because we checked at the top
      const messageId = wsMessage.message_id!;
      console.log('⏳ No mapping yet - storing pending message:', messageId);
      pendingMessagesRef.current.set(messageId, wsMessage);

      // Set a timeout to create the message if no mapping arrives within 500ms
      setTimeout(() => {
        const stillPending = pendingMessagesRef.current.get(messageId);
        if (stillPending) {
          console.log('⚠️ Timeout - creating message without mapping:', messageId);
          pendingMessagesRef.current.delete(messageId);

          const existingMessage = messages.find((m) => m.id === messageId);
          if (!existingMessage) {
            console.log('➕ Creating new sender_confirmation message:', messageId);
            const newMessage: Message = {
              id: messageId,
              sender: clientType || 'admin',
              content_type: wsMessage.audio_url ? 'audio' : 'text',
              content: wsMessage.text,
              audio_url: wsMessage.audio_url,
              timestamp: new Date().toISOString(),
              status: 'sent',
              pipeline_metadata: wsMessage.pipeline_metadata,
            };
            addMessage(newMessage);
          }
        }
      }, 500);

      return; // Don't create new message for sender_confirmation
    }

    if (wsMessage.role === 'receiver_message') {
      // This is a message from the other party (translated for us)
      // Check if message already exists to prevent duplicates
      if (!wsMessage.message_id) {
        console.error('❌ receiver_message without message_id');
        return;
      }
      
      console.log('📥 receiver_message received:', wsMessage.message_id);
      
      // Use functional state update to get current messages
      setMessages((currentMessages) => {
        const existingMessage = currentMessages.find((m) => m.id === wsMessage.message_id);
        if (existingMessage) {
          console.log('⚠️ receiver_message already exists, skipping:', wsMessage.message_id);
          return currentMessages;
        }
        
        console.log('✅ Creating new receiver message:', wsMessage.message_id);
        const newMessage: Message = {
          id: wsMessage.message_id!,
          sender: clientType === 'admin' ? 'customer' : 'admin',
          content_type: wsMessage.audio_url ? 'audio' : 'text',
          content: wsMessage.text,  // The translated text for us
          translation_audio_url: wsMessage.audio_url,  // Audio der Übersetzung
          timestamp: new Date().toISOString(),
          status: 'sent',
          pipeline_metadata: wsMessage.pipeline_metadata,
        };
        return [...currentMessages, newMessage];
      });
      return;
    }
  };

  const startSession = (newSessionId: string, newClientType: ClientType, newCustomerLanguage?: string) => {
    setSessionId(newSessionId);
    setClientType(newClientType);
    setIsActive(true);
    if (newCustomerLanguage) {
      setCustomerLanguage(newCustomerLanguage);
    }
    // Don't clear messages - they may have been loaded from history
  };

  const endSession = () => {
    WebSocketService.disconnect();
    setSessionId(null);
    setClientType(null);
    setIsActive(false);
    setMessages([]);
  };

  const addMessage = (message: Message) => {
    console.log('🔵 addMessage called:', message.id, message.content?.substring(0, 20));

    setMessages((prev) => {
      // Check if message already exists
      const exists = prev.find((m) => m.id === message.id);
      if (exists) {
        console.warn('⚠️ Message already exists, skipping:', message.id);
        return prev;
      }
      return [...prev, message];
    });
  };

  const updateMessage = (messageId: string, updates: Partial<Message>) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === messageId ? { ...msg, ...updates } : msg))
    );
  };

  const registerTempId = (tempId: string, realId: string) => {
    console.log('🔗 registerTempId called:', tempId, '->', realId);
    tempIdMapRef.current.set(tempId, realId);

    // Check if we have a pending WebSocket message for this realId
    const pendingMessage = pendingMessagesRef.current.get(realId);
    if (pendingMessage) {
      console.log('✅ Found pending message - processing now:', realId);
      pendingMessagesRef.current.delete(realId);

      // Update the optimistic message with WebSocket data
      console.log('✏️ Updating temp message with pending data:', tempId);
      updateMessage(tempId, {
        status: 'sent',
        content: pendingMessage.text,
        pipeline_metadata: pendingMessage.pipeline_metadata,
        audio_url: pendingMessage.audio_url,
      });
    }
  };

  return (
    <SessionContext.Provider
      value={{
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
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
}
