import { useState, useRef, useEffect } from 'react';
import { useSession } from '../contexts/SessionContext';
import MessageService from '../services/MessageService';
import { AudioRecorderWithWAVConversion } from '../utils/AudioRecorderWithWAVConversion';
import api from '../services/api';

type InputMode = 'text' | 'audio';
type RecordingState = 'idle' | 'recording' | 'processing';

interface MessageInputProps {
  disabled?: boolean;
}

export default function MessageInput({ disabled = false }: MessageInputProps) {
  const { sessionId, clientType, addMessage, updateMessage, customerLanguage, adminLanguage, registerTempId, isActive } = useSession();
  const [inputMode, setInputMode] = useState<InputMode>('text');
  const [textMessage, setTextMessage] = useState('');
  const [recordingState, setRecordingState] = useState<RecordingState>('idle');
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Disable input until session is active (customer has joined)
  const isInputDisabled = disabled || !isActive;

  const recordingIntervalRef = useRef<number | null>(null);
  const audioRecorderRef = useRef<AudioRecorderWithWAVConversion | null>(null);

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
      // Create audio recorder instance with WAV conversion
      const recorder = new AudioRecorderWithWAVConversion({
        sampleRate: 16000,
        bitDepth: 16,
        channels: 1,
        maxDurationMs: 20000,
        onStart: () => {
          setRecordingState('recording');
          setRecordingDuration(0);
          setError(null);

          // Start duration counter
          recordingIntervalRef.current = window.setInterval(() => {
            setRecordingDuration((prev) => prev + 1);
          }, 1000);
        },
        onStop: () => {
          setRecordingState('processing');
          if (recordingIntervalRef.current) {
            clearInterval(recordingIntervalRef.current);
            recordingIntervalRef.current = null;
          }
        },
        onDataAvailable: async (wavBlob) => {
          // WAV conversion successful, upload to backend
          await sendAudioMessage(wavBlob);
        },
        onError: (error) => {
          console.error('Recording error:', error);
          setError(error.message || 'Fehler bei der Audio-Aufnahme');
          setRecordingState('idle');
        },
      });

      audioRecorderRef.current = recorder;
      await recorder.startRecording();
    } catch (err) {
      console.error('Failed to start recording:', err);
      setError('Mikrofon-Zugriff verweigert. Bitte Berechtigungen prüfen.');
      setRecordingState('idle');
    }
  };

  const stopRecording = () => {
    if (audioRecorderRef.current && recordingState === 'recording') {
      // Sofort visuelles Feedback geben
      setRecordingState('processing');
      if (recordingIntervalRef.current) {
        clearInterval(recordingIntervalRef.current);
        recordingIntervalRef.current = null;
      }
      // Aufnahme tatsächlich stoppen (Konvertierung läuft im Hintergrund)
      audioRecorderRef.current.stopRecording();
    }
  };

  const sendAudioMessage = async (wavBlob: Blob) => {
    if (!sessionId || !clientType) return;
    // Admin needs customerLanguage, customer uses their own language from session context
    if (clientType === 'admin' && !customerLanguage) return;

    // Determine source and target language based on client type
    const source_lang = clientType === 'admin' ? adminLanguage : customerLanguage!;
    const target_lang = clientType === 'admin' ? customerLanguage! : adminLanguage;

    const tempMessageId = `temp-${Date.now()}`;
    const optimisticMessage = {
      id: tempMessageId,
      sender: clientType,
      content_type: 'audio' as const,
      content: '[Audio-Nachricht]',
      timestamp: new Date().toISOString(),
      status: 'sending' as const,
    };

    addMessage(optimisticMessage);
    setError(null);

    try {
      console.log('📡 Uploading audio message with temp ID:', tempMessageId);

      // Create FormData for multipart/form-data upload
      const formData = new FormData();
      formData.append('file', wavBlob, 'recording.wav');
      formData.append('source_lang', source_lang);
      formData.append('target_lang', target_lang);
      formData.append('client_type', clientType);

      // Upload audio via POST /api/session/{sessionId}/message
      const response = await api.post<{
        message_id: string;
        status: string;
        message: string;
      }>(`/api/session/${sessionId}/message`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      console.log('✅ Audio upload successful:', response.data.message_id);

      // Register the mapping from temp ID to real ID
      registerTempId(tempMessageId, response.data.message_id);
      console.log('🔗 Registered mapping:', tempMessageId, '->', response.data.message_id);

      // Mark as sent
      updateMessage(tempMessageId, {
        status: 'sent',
      });

      // Reset recording state
      setRecordingState('idle');
    } catch (err: unknown) {
      console.error('Failed to send audio message:', err);
      updateMessage(tempMessageId, {
        status: 'error',
      });

      // Extract user-friendly error message from API response
      let errorMessage = 'Fehler beim Senden der Audio-Nachricht';
      const error = err as { response?: { data?: { detail?: { error_message?: string; message?: string } | string } }; message?: string };
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === 'object' && detail.error_message) {
          errorMessage = detail.error_message;
        } else if (typeof detail === 'object' && detail.message) {
          errorMessage = detail.message;
        } else if (typeof detail === 'string') {
          errorMessage = detail;
        }
      } else if (error.message) {
        errorMessage = error.message;
      }

      setError(errorMessage);
      setRecordingState('idle');
    }
  };

  const sendTextMessage = async () => {
    console.log('🔍 sendTextMessage called:', {
      textMessage: textMessage.substring(0, 20),
      sessionId,
      clientType,
      customerLanguage,
      isActive
    });

    if (!textMessage.trim() || !sessionId || !clientType) {
      console.log('❌ Basic validation failed');
      return;
    }

    // Admin needs customerLanguage, customer uses their own language from session context
    if (clientType === 'admin' && !customerLanguage) {
      console.log('❌ Admin missing customerLanguage');
      return;
    }

    // Determine source and target language based on client type
    const source_lang = clientType === 'admin' ? adminLanguage : customerLanguage!;
    const target_lang = clientType === 'admin' ? customerLanguage! : adminLanguage;

    console.log('✅ Sending message:', { source_lang, target_lang, clientType });

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
    } catch (err: unknown) {
      console.error('Failed to send text message:', err);
      updateMessage(tempMessageId, {
        status: 'error',
      });

      // Extract user-friendly error message from API response
      let errorMessage = 'Fehler beim Senden der Nachricht';
      const error = err as { response?: { data?: { detail?: { error_message?: string; message?: string } | string } }; message?: string };
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail;
        if (typeof detail === 'object' && detail.error_message) {
          errorMessage = detail.error_message;
        } else if (typeof detail === 'object' && detail.message) {
          errorMessage = detail.message;
        } else if (typeof detail === 'string') {
          errorMessage = detail;
        }
      } else if (error.message) {
        errorMessage = error.message;
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
          disabled={isInputDisabled || recordingState !== 'idle'}
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
          disabled={isInputDisabled || recordingState !== 'idle'}
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
            placeholder={!isActive ? "Warten auf Teilnehmer..." : "Nachricht eingeben..."}
            disabled={isInputDisabled}
            rows={2}
            className="flex-1 px-3 sm:px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed resize-none text-sm sm:text-base"
          />
          <button
            onClick={sendTextMessage}
            disabled={isInputDisabled || !textMessage.trim()}
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
              disabled={isInputDisabled}
              className="w-16 h-16 sm:w-20 sm:h-20 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center text-2xl sm:text-3xl transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              🎤
            </button>
          )}

          {recordingState === 'recording' && (
            <div className="flex flex-col items-center space-y-3">
              <button
                onClick={stopRecording}
                className="w-16 h-16 sm:w-20 sm:h-20 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center relative cursor-pointer z-10"
                type="button"
              >
                <div className="absolute inset-0 bg-red-500 rounded-full animate-ping opacity-75 pointer-events-none" />
                <span className="relative text-2xl sm:text-3xl z-10">⏹️</span>
              </button>
              <div className="text-base sm:text-lg font-mono font-semibold text-gray-700">
                {formatDuration(recordingDuration)}
              </div>
              <div className="text-xs sm:text-sm text-gray-600">Aufnahme läuft... (Klicken zum Stoppen)</div>
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
