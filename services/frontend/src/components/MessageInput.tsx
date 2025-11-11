import { useState, useRef, useEffect } from 'react';
import { useSession } from '../contexts/SessionContext';
import MessageService from '../services/MessageService';

type InputMode = 'text' | 'audio';
type RecordingState = 'idle' | 'recording' | 'processing';

interface MessageInputProps {
  disabled?: boolean;
}

export default function MessageInput({ disabled = false }: MessageInputProps) {
  const { sessionId, clientType, addMessage, updateMessage, customerLanguage, adminLanguage, registerTempId } = useSession();
  const [inputMode, setInputMode] = useState<InputMode>('text');
  const [textMessage, setTextMessage] = useState('');
  const [recordingState, setRecordingState] = useState<RecordingState>('idle');
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      stopRecording();
      if (recordingIntervalRef.current) {
        clearInterval(recordingIntervalRef.current);
      }
    };
  }, []);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm',
      });

      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await sendAudioMessage(audioBlob);
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start();
      setRecordingState('recording');
      setRecordingDuration(0);
      setError(null);

      // Start duration counter
      recordingIntervalRef.current = setInterval(() => {
        setRecordingDuration((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('Failed to start recording:', err);
      setError('Mikrofon-Zugriff verweigert. Bitte Berechtigungen prüfen.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && recordingState === 'recording') {
      mediaRecorderRef.current.stop();
      setRecordingState('processing');
      if (recordingIntervalRef.current) {
        clearInterval(recordingIntervalRef.current);
        recordingIntervalRef.current = null;
      }
    }
  };

  const sendAudioMessage = async (_audioBlob: Blob) => {
    if (!sessionId || !clientType) return;

    // TODO: Audio messages need multipart/form-data format
    // Currently not supported - need to implement file upload
    setError('Audio-Nachrichten werden noch nicht unterstützt');
    setRecordingState('idle');
  };

  const sendTextMessage = async () => {
    if (!textMessage.trim() || !sessionId || !clientType) return;

    // Determine source and target language based on client type
    const source_lang = clientType === 'admin' ? adminLanguage : (customerLanguage || 'en');
    const target_lang = clientType === 'admin' ? (customerLanguage || 'en') : adminLanguage;

    const tempMessageId = `temp-${Date.now()}`;
    const optimisticMessage = {
      id: tempMessageId,
      sender: clientType,
      content_type: 'text' as const,
      content: textMessage.trim(),
      timestamp: new Date().toISOString(),
      status: 'sending' as const,
    };

    addMessage(optimisticMessage);
    setTextMessage('');
    setError(null);

    try {
      console.log('📡 Sending message with temp ID:', tempMessageId);
      const response = await MessageService.sendMessage(sessionId, {
        text: textMessage.trim(),
        source_lang,
        target_lang,
        client_type: clientType,
      });

      console.log('✅ API Response received:', response.message_id);
      // Register the mapping from temp ID to real ID IMMEDIATELY
      // This must happen before WebSocket message arrives!
      registerTempId(tempMessageId, response.message_id);
      console.log('🔗 Registered mapping:', tempMessageId, '->', response.message_id);

      // Don't update the ID - WebSocket will handle the final update
      // Just mark as sent to show it was accepted by server
      updateMessage(tempMessageId, {
        status: 'sent',
      });
    } catch (err: any) {
      console.error('Failed to send text message:', err);
      updateMessage(tempMessageId, {
        status: 'error',
      });

      // Extract user-friendly error message from API response
      let errorMessage = 'Fehler beim Senden der Nachricht';
      if (err.response?.data?.detail?.error_message) {
        errorMessage = err.response.data.detail.error_message;
      } else if (err.response?.data?.detail?.message) {
        errorMessage = err.response.data.detail.message;
      } else if (err.response?.data?.detail) {
        errorMessage = typeof err.response.data.detail === 'string'
          ? err.response.data.detail
          : 'Fehler beim Senden der Nachricht';
      } else if (err.message) {
        errorMessage = err.message;
      }

      setError(errorMessage);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTextMessage();
    }
  };

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-white border-t border-gray-200 p-3 sm:p-4">
      {error && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      {/* Mode Toggle */}
      <div className="flex items-center justify-center mb-3 space-x-2">
        <button
          onClick={() => setInputMode('text')}
          disabled={disabled || recordingState !== 'idle'}
          className={`px-3 sm:px-4 py-2 rounded-lg font-medium transition-colors text-sm sm:text-base ${
            inputMode === 'text'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          📝 Text
        </button>
        <button
          onClick={() => setInputMode('audio')}
          disabled={disabled || recordingState !== 'idle'}
          className={`px-3 sm:px-4 py-2 rounded-lg font-medium transition-colors text-sm sm:text-base ${
            inputMode === 'audio'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          🎤 Audio
        </button>
      </div>

      {/* Text Input Mode */}
      {inputMode === 'text' && (
        <div className="flex items-end space-x-2">
          <textarea
            value={textMessage}
            onChange={(e) => setTextMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Nachricht eingeben..."
            disabled={disabled}
            rows={2}
            className="flex-1 px-3 sm:px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed resize-none text-sm sm:text-base"
          />
          <button
            onClick={sendTextMessage}
            disabled={disabled || !textMessage.trim()}
            className="px-4 sm:px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-semibold transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed min-h-[76px] text-sm sm:text-base"
          >
            Senden
          </button>
        </div>
      )}

      {/* Audio Input Mode */}
      {inputMode === 'audio' && (
        <div className="flex flex-col items-center py-2">
          {recordingState === 'idle' && (
            <button
              onClick={startRecording}
              disabled={disabled}
              className="w-16 h-16 sm:w-20 sm:h-20 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center text-2xl sm:text-3xl transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              🎤
            </button>
          )}

          {recordingState === 'recording' && (
            <div className="flex flex-col items-center space-y-3">
              <button
                onClick={stopRecording}
                className="w-16 h-16 sm:w-20 sm:h-20 bg-red-500 text-white rounded-full flex items-center justify-center relative"
              >
                <div className="absolute inset-0 bg-red-500 rounded-full animate-ping opacity-75" />
                <span className="relative text-2xl sm:text-3xl">⏹️</span>
              </button>
              <div className="text-base sm:text-lg font-mono font-semibold text-gray-700">
                {formatDuration(recordingDuration)}
              </div>
              <div className="text-xs sm:text-sm text-gray-600">Aufnahme läuft...</div>
            </div>
          )}

          {recordingState === 'processing' && (
            <div className="flex flex-col items-center space-y-3">
              <div className="w-16 h-16 sm:w-20 sm:h-20 bg-indigo-500 text-white rounded-full flex items-center justify-center">
                <div className="animate-spin rounded-full h-6 w-6 sm:h-8 sm:w-8 border-b-2 border-white" />
              </div>
              <div className="text-xs sm:text-sm text-gray-600">Wird verarbeitet...</div>
            </div>
          )}
        </div>
      )}

      {disabled && (
        <div className="mt-3 text-center text-xs sm:text-sm text-gray-500">
          Nachrichtenversand ist deaktiviert
        </div>
      )}
    </div>
  );
}
