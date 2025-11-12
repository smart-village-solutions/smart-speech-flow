import { useState, useEffect, useRef } from 'react';
import type { Message } from '../contexts/SessionContext';

interface MessageBubbleProps {
  message: Message;
  isOwnMessage: boolean;
  showMetadata?: boolean;
}

export default function MessageBubble({ message, isOwnMessage, showMetadata = false }: MessageBubbleProps) {
  const [showMetadataModal, setShowMetadataModal] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const hasAutoPlayed = useRef(false);

  // Autoplay für empfangene Nachrichten
  useEffect(() => {
    if (!isOwnMessage && message.translation_audio_url && !hasAutoPlayed.current && message.status === 'sent') {
      hasAutoPlayed.current = true;
      playAudio(message.translation_audio_url);
    }
  }, [message.translation_audio_url, isOwnMessage, message.status]);

  const playAudio = async (url: string) => {
    try {
      // Verwende absolute URL für Audio
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
      const absoluteUrl = url.startsWith('http') ? url : `${apiBaseUrl}${url}`;

      console.log('🔊 Playing audio from:', absoluteUrl);
      const audio = new Audio(absoluteUrl);
      audio.onplay = () => setAudioPlaying(true);
      audio.onended = () => setAudioPlaying(false);
      audio.onerror = (e) => {
        console.error('Audio playback error:', e);
        setAudioPlaying(false);
      };
      await audio.play();
    } catch (err) {
      console.error('Failed to play audio:', err);
    }
  };

  const formatTime = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <>
      <div className={`flex ${isOwnMessage ? 'justify-end' : 'justify-start'} mb-4`}>
        <div className={`max-w-[70%] ${isOwnMessage ? 'items-end' : 'items-start'} flex flex-col`}>
          {/* Message Bubble */}
          <div
            onClick={() => showMetadata && message.pipeline_metadata && setShowMetadataModal(true)}
            className={`rounded-lg px-4 py-3 ${
              isOwnMessage
                ? 'bg-indigo-600 text-white rounded-br-none'
                : 'bg-gray-200 text-gray-900 rounded-bl-none'
            } ${showMetadata && message.pipeline_metadata ? 'cursor-pointer hover:opacity-90 transition-opacity' : ''}`}
          >
          {/* Sending/Error Status */}
          {message.status === 'sending' && (
            <div className="flex items-center space-x-2 mb-2">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-sm opacity-75">Wird gesendet...</span>
            </div>
          )}

          {message.status === 'error' && (
            <div className="flex items-center space-x-2 mb-2 text-red-200">
              <span>⚠️</span>
              <span className="text-sm">Fehler beim Senden</span>
            </div>
          )}

          {/* Original Content (for own messages) */}
          {isOwnMessage && message.content && message.content_type === 'audio' && (
            <div className="mb-2 text-sm opacity-90 italic">
              "{message.content}"
            </div>
          )}

          {isOwnMessage && message.recognized_text && (
            <div className="mb-2 text-sm opacity-90 italic">
              "{message.recognized_text}"
            </div>
          )}

          {/* Text Content */}
          {message.content && message.content_type === 'text' && (
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          )}

          {/* Translation (for received messages) */}
          {!isOwnMessage && message.translation && (
            <div className="mt-2 pt-2 border-t border-gray-300">
              <div className="text-sm font-semibold mb-1">Übersetzung:</div>
              <div>{message.translation}</div>
            </div>
          )}
        </div>

          {/* Audio Player - außerhalb des klickbaren Bereichs */}
          {message.translation_audio_url && !isOwnMessage && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                playAudio(message.translation_audio_url!);
              }}
              disabled={audioPlaying}
              className={`mt-2 flex items-center space-x-2 px-3 py-1 rounded ${
                isOwnMessage
                  ? 'bg-indigo-700 hover:bg-indigo-800'
                  : 'bg-gray-300 hover:bg-gray-400'
              } transition-colors disabled:opacity-50`}
            >
              <span>{audioPlaying ? '⏸️' : '▶️'}</span>
              <span className="text-sm">Audio abspielen</span>
            </button>
          )}

        {/* Timestamp */}
        <div className="text-xs text-gray-500 mt-1 px-1">
          {formatTime(message.timestamp)}
          {showMetadata && message.pipeline_metadata && (
            <span className="ml-2 text-indigo-500">• Details anzeigen</span>
          )}
        </div>
      </div>
    </div>

      {/* Pipeline Metadata Modal */}
      {showMetadataModal && message.pipeline_metadata && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
          onClick={() => setShowMetadataModal(false)}
        >
          <div
            className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">Pipeline Details</h3>
              <button
                onClick={() => setShowMetadataModal(false)}
                className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
              >
                ×
              </button>
            </div>

            {/* Content */}
            <div className="px-6 py-4 space-y-4">
              {/* Total Duration */}
              {message.pipeline_metadata.total_duration_ms && (
                <div className="bg-indigo-50 rounded-lg p-4">
                  <div className="text-sm text-gray-600 mb-1">Gesamtdauer</div>
                  <div className="text-2xl font-bold text-indigo-600">
                    {message.pipeline_metadata.total_duration_ms}ms
                  </div>
                </div>
              )}

              {/* Input Info */}
              {message.pipeline_metadata.input && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <div className="font-semibold text-gray-900 mb-2">Input</div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <span className="text-gray-600">Typ:</span>{' '}
                      <span className="font-medium">{message.pipeline_metadata.input.type}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Sprache:</span>{' '}
                      <span className="font-medium">{message.pipeline_metadata.input.source_lang}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Pipeline Steps */}
              {message.pipeline_metadata.steps && message.pipeline_metadata.steps.length > 0 && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <div className="font-semibold text-gray-900 mb-3">Pipeline Schritte</div>
                  <div className="space-y-3">
                    {message.pipeline_metadata.steps.map((step, idx) => (
                      <div key={idx} className="bg-gray-50 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <div className="font-medium text-gray-900">
                            {idx + 1}. {step.name}
                          </div>
                          <div className="text-sm text-indigo-600 font-medium">
                            {step.duration_ms}ms
                          </div>
                        </div>
                        {step.output && Object.keys(step.output).length > 0 && (
                          <div className="mt-2 p-2 bg-white rounded border border-gray-200">
                            <div className="text-xs text-gray-600 mb-1">Output:</div>
                            <pre className="text-xs text-gray-800 whitespace-pre-wrap overflow-x-auto">
                              {JSON.stringify(step.output, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Timestamp */}
              {message.pipeline_metadata.pipeline_started_at && (
                <div className="text-xs text-gray-500 text-center pt-2 border-t border-gray-200">
                  Pipeline gestartet: {new Date(message.pipeline_metadata.pipeline_started_at).toLocaleString('de-DE')}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
