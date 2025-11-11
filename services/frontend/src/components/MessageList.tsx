import { useEffect, useRef } from 'react';
import { useSession } from '../contexts/SessionContext';
import MessageBubble from './MessageBubble';

interface MessageListProps {
  showMetadata?: boolean;
}

export default function MessageList({ showMetadata = false }: MessageListProps) {
  const { messages, clientType } = useSession();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const previousMessageCountRef = useRef(0);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > previousMessageCountRef.current) {
      scrollToBottom();
    }
    previousMessageCountRef.current = messages.length;
  }, [messages.length]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 sm:p-8">
        <div className="text-center text-gray-500">
          <div className="text-3xl sm:text-4xl mb-2 sm:mb-3">💬</div>
          <div className="text-base sm:text-lg font-medium mb-1 sm:mb-2">Noch keine Nachrichten</div>
          <div className="text-xs sm:text-sm px-4">Senden Sie eine Nachricht, um die Konversation zu starten</div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-2"
      style={{ maxHeight: 'calc(100vh - 250px)' }}
    >
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          isOwnMessage={message.sender === clientType}
          showMetadata={showMetadata}
        />
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
}
