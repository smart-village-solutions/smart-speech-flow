import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import SessionService from '../services/SessionService';
import MessageService from '../services/MessageService';
import { useSession } from '../contexts/SessionContext';
import MessageList from '../components/MessageList';
import MessageInput from '../components/MessageInput';
import ConnectionStatusIndicator from '../components/ConnectionStatusIndicator';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';

export default function AdminPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<'idle' | 'creating' | 'pending' | 'active'>('idle');
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const {
    sessionId: activeSessionId,
    clientType: activeClientType,
    startSession,
    endSession,
    isActive,
    addMessage,
  } = useSession();

  // Start WebSocket connection immediately when session is created (pending or active)
  useEffect(() => {
    const needsAdminConnection =
      sessionId &&
      (sessionStatus === 'pending' || sessionStatus === 'active') &&
      (activeSessionId !== sessionId || activeClientType !== 'admin');

    if (needsAdminConnection) {
      startSession(sessionId, 'admin');

      // Start the session connection immediately, then hydrate state from the API.
      Promise.all([
        SessionService.getSessionStatus(sessionId),
        MessageService.getMessages(sessionId)
      ])
        .then(([sessionInfo, history]) => {
          history.forEach((msg) => addMessage(msg));
          // Start session with customer language if available
          startSession(sessionId, 'admin', sessionInfo.customer_language || undefined);
        })
        .catch((err) => {
          console.warn('Failed to load session data:', err);
        });
    }
  }, [sessionId, sessionStatus, activeSessionId, activeClientType, startSession, addMessage]);

  // Update session status when session becomes active via WebSocket
  useEffect(() => {
    if (isActive && sessionStatus === 'pending') {
      setSessionStatus('active');
    }
  }, [isActive, sessionStatus]);

  const handleCreateSession = async () => {
    setSessionStatus('creating');
    setError(null);

    try {
      if (activeSessionId || isActive) {
        endSession();
      }

      const response = await SessionService.createSession();
      setSessionId(response.session_id);
      setSessionStatus(response.status === 'active' ? 'active' : 'pending');
    } catch (err) {
      console.error('Failed to create session:', err);
      setError('Fehler beim Erstellen der Session. Bitte versuchen Sie es erneut.');
      setSessionStatus('idle');
    }
  };

  const handleTerminateSession = async () => {
    if (!sessionId) return;

    try {
      await SessionService.terminateSession(sessionId);
      endSession();
      setSessionId(null);
      setSessionStatus('idle');
      setError(null);
    } catch (err) {
      console.error('Failed to terminate session:', err);
      setError('Fehler beim Beenden der Session.');
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 flex flex-col w-full">
        <div className="bg-white shadow-card">
          <div className="w-full px-4 sm:px-6 lg:px-8 py-6">
            <div className="flex items-center justify-between">
              <h1 className="text-2xl sm:text-3xl font-bold text-text leading-tight">
                Admin - Session Verwaltung
              </h1>
              <button
                onClick={() => navigate('/')}
                className="text-primary hover:text-primary-dark font-semibold text-base sm:text-lg transition-colors"
              >
                Zurück
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 w-full px-4 sm:px-6 lg:px-8 py-4">
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
              {error}
            </div>
          )}

          {sessionStatus === 'idle' && (
            <div className="bg-white rounded-card-lg shadow-card p-8 mb-8">
              <button
                onClick={handleCreateSession}
                className="w-full bg-primary hover:brightness-90 text-white font-semibold py-4 px-8 rounded-card transition duration-200 text-lg"
              >
                Neue Session erstellen
              </button>
            </div>
          )}

          {sessionStatus === 'creating' && (
            <div className="bg-white rounded-card-lg shadow-card p-8 mb-8 text-center py-12">
              <div className="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
              <p className="mt-4 text-gray-600 text-lg">Session wird erstellt...</p>
            </div>
          )}

          {(sessionStatus === 'pending' || sessionStatus === 'active') && sessionId && (
            <div className="grid grid-cols-1 gap-8">
              <div className="bg-white rounded-card-lg shadow-card p-6 sm:p-8">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6 mb-4">
                  <div className="flex-1">
                    <div className="text-sm text-gray-600 mb-2 font-semibold">Session ID:</div>
                    <div className="text-2xl sm:text-3xl font-mono font-bold text-primary-dark tracking-wider break-all">
                      {sessionId}
                    </div>
                  </div>
                  <ConnectionStatusIndicator />
                </div>
                <div className="mt-3 flex items-center text-sm flex-wrap">
                  <span className="mr-2 font-semibold text-text">Status:</span>
                  {sessionStatus === 'pending' && (
                    <span className="inline-flex items-center px-4 py-2 rounded-card text-yellow-800 bg-yellow-100 font-semibold">
                      <span className="mr-2">⏳</span>
                      {' '}
                      Warte auf Kunde
                    </span>
                  )}
                  {sessionStatus === 'active' && (
                    <span className="inline-flex items-center px-4 py-2 rounded-card text-green-800 bg-green-100 font-semibold">
                      <span className="mr-2">✅</span>
                      {' '}
                      Aktiv
                    </span>
                  )}
                </div>
              </div>

              {sessionStatus === 'active' && (
                <div className="bg-white rounded-card-lg shadow-card overflow-hidden flex flex-col" style={{ height: 'calc(100vh - 320px)', minHeight: '400px' }}>
                  <MessageList showMetadata={true} />
                  <MessageInput disabled={!isActive} />
                </div>
              )}

              <div className="bg-white rounded-card-lg shadow-card p-6 sm:p-8">
                <button
                  onClick={handleTerminateSession}
                  className="w-full bg-red-600 hover:brightness-90 text-white font-semibold py-4 px-8 rounded-card transition duration-200 text-lg"
                >
                  Session beenden
                </button>
              </div>
            </div>
          )}

          {sessionStatus === 'idle' && (
            <div className="bg-white rounded-card-lg shadow-card p-6 sm:p-8">
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Anleitung
              </h2>
              <ol className="list-decimal list-inside space-y-2 text-gray-700 text-sm sm:text-base">
                <li>Klicken Sie auf "Neue Session erstellen"</li>
                <li>Teilen Sie die Session-ID dem Kunden mit</li>
                <li>Warten Sie, bis der Kunde beitritt</li>
                <li>Starten Sie die Kommunikation</li>
              </ol>
            </div>
          )}
        </div>
      </div>
      <Footer />
    </div>
  );
}
