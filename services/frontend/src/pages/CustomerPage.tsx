import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import CustomerService from '../services/CustomerService';
import MessageService from '../services/MessageService';
import type { Language } from '../services/CustomerService';
import { useSession } from '../contexts/SessionContext';
import MessageList from '../components/MessageList';
import MessageInput from '../components/MessageInput';
import ConnectionStatusIndicator from '../components/ConnectionStatusIndicator';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';

type ViewMode = 'input' | 'language' | 'active';

export default function CustomerPage() {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const { startSession, isActive, addMessage } = useSession();

  const [viewMode, setViewMode] = useState<ViewMode>(urlSessionId ? 'language' : 'input');
  const [sessionId, setSessionId] = useState<string>(urlSessionId || '');
  const [sessionIdError, setSessionIdError] = useState<string | null>(null);
  const [selectedLanguage, setSelectedLanguage] = useState<string>('');
  const [languages, setLanguages] = useState<Language[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load languages on mount
  useEffect(() => {
    loadLanguages();
  }, []);

  const loadLanguages = async () => {
    try {
      const langs = await CustomerService.getLanguages();
      setLanguages(langs);
    } catch (err) {
      console.error('Failed to load languages:', err);
      // Fallback to hardcoded languages if API fails
      setLanguages([
        { code: 'en', name: 'English' },
        { code: 'es', name: 'Spanish' },
        { code: 'fr', name: 'French' },
        { code: 'it', name: 'Italian' },
        { code: 'tr', name: 'Turkish' },
        { code: 'ar', name: 'Arabic' },
        { code: 'ru', name: 'Russian' },
        { code: 'pl', name: 'Polish' },
        { code: 'uk', name: 'Ukrainian' },
      ]);
    }
  };

  const validateSessionId = (id: string): boolean => {
    const regex = /^[A-Z0-9]{8}$/;
    return regex.test(id);
  };

  const handleSessionIdChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.toUpperCase();
    setSessionId(value);
    setSessionIdError(null);
  };

  const handleSessionIdSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateSessionId(sessionId)) {
      setSessionIdError('Session-ID muss genau 8 Zeichen (Großbuchstaben und Zahlen) sein');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Verify session exists
      const isValid = await CustomerService.verifySession(sessionId);
      if (!isValid) {
        setSessionIdError('Session nicht gefunden oder nicht mehr verfügbar');
        setLoading(false);
        return;
      }

      setViewMode('language');
    } catch (err) {
      console.error('Failed to verify session:', err);
      setError('Fehler beim Überprüfen der Session. Bitte versuchen Sie es erneut.');
    } finally {
      setLoading(false);
    }
  };

  // Input view: Enter session ID
  if (viewMode === 'input') {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Header />
        <div className="flex-1 flex items-center justify-center px-4 py-12 sm:py-20">
        <div className="bg-white rounded-card-lg shadow-card p-8 sm:p-12 w-full max-w-lg">
          <div className="flex items-center justify-between mb-8">
            <h1 className="text-2xl sm:text-3xl font-bold text-text leading-tight">Session beitreten</h1>
            <button
              onClick={() => navigate('/')}
              className="text-primary hover:text-primary-dark font-semibold text-base sm:text-lg transition-colors"
            >
              Zurück
            </button>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-card text-red-800">
              {error}
            </div>
          )}

          <form onSubmit={handleSessionIdSubmit} className="grid grid-cols-1 gap-6">
            <div>
              <label htmlFor="sessionId" className="block text-base font-semibold text-text mb-3">
                Session-ID eingeben:
              </label>
              <input
                id="sessionId"
                type="text"
                value={sessionId}
                onChange={handleSessionIdChange}
                maxLength={8}
                placeholder="Z.B. ABC12345"
                className={`w-full px-6 py-4 text-lg sm:text-xl font-mono uppercase border rounded-card focus:outline-none focus:ring-2 ${
                  sessionIdError
                    ? 'border-red-300 focus:ring-red-500'
                    : 'border-gray-300 focus:ring-primary'
                }`}
              />
              {sessionIdError && (
                <p className="mt-2 text-base text-red-600">{sessionIdError}</p>
              )}
              <p className="mt-3 text-sm text-gray-500 leading-relaxed">
                Die Session-ID besteht aus 8 Zeichen (Großbuchstaben und Zahlen)
              </p>
            </div>

            <button
              type="submit"
              disabled={loading || !sessionId}
              className="w-full bg-primary hover:brightness-90 disabled:bg-gray-400 text-white font-semibold py-4 px-8 rounded-card transition duration-200 text-lg"
            >
            {loading ? 'Überprüfen...' : 'Weiter'}
          </button>
        </form>
      </div>
      </div>
      <Footer />
    </div>
  );
  }

  // Language selection view
  if (viewMode === 'language') {
    // Map language codes to flag emojis and native names
    const languageFlags: Record<string, { flag: string; native: string; english: string }> = {
      'de': { flag: '🇩🇪', native: 'Deutsch', english: 'German' },
      'en': { flag: '🇬🇧', native: 'English', english: 'English' },
      'es': { flag: '🇪🇸', native: 'Español', english: 'Spanish' },
      'fr': { flag: '🇫🇷', native: 'Français', english: 'French' },
      'it': { flag: '🇮🇹', native: 'Italiano', english: 'Italian' },
      'tr': { flag: '🇹🇷', native: 'Türkçe', english: 'Turkish' },
      'ar': { flag: '🇸🇦', native: 'العربية', english: 'Arabic' },
      'ru': { flag: '🇷🇺', native: 'Русский', english: 'Russian' },
      'pl': { flag: '🇵🇱', native: 'Polski', english: 'Polish' },
      'uk': { flag: '🇺🇦', native: 'Українська', english: 'Ukrainian' },
      'zh': { flag: '🇨🇳', native: '中文', english: 'Chinese' },
      'ja': { flag: '🇯🇵', native: '日本語', english: 'Japanese' },
      'ko': { flag: '🇰🇷', native: '한국어', english: 'Korean' },
      'pt': { flag: '🇵🇹', native: 'Português', english: 'Portuguese' },
      'nl': { flag: '🇳🇱', native: 'Nederlands', english: 'Dutch' },
      'sv': { flag: '🇸🇪', native: 'Svenska', english: 'Swedish' },
      'da': { flag: '🇩🇰', native: 'Dansk', english: 'Danish' },
      'no': { flag: '🇳🇴', native: 'Norsk', english: 'Norwegian' },
      'fi': { flag: '🇫🇮', native: 'Suomi', english: 'Finnish' },
      'cs': { flag: '🇨🇿', native: 'Čeština', english: 'Czech' },
      'el': { flag: '🇬🇷', native: 'Ελληνικά', english: 'Greek' },
      'ro': { flag: '🇷🇴', native: 'Română', english: 'Romanian' },
      'hu': { flag: '🇭🇺', native: 'Magyar', english: 'Hungarian' },
      'bg': { flag: '🇧🇬', native: 'Български', english: 'Bulgarian' },
      'hr': { flag: '🇭🇷', native: 'Hrvatski', english: 'Croatian' },
      'sk': { flag: '🇸🇰', native: 'Slovenčina', english: 'Slovak' },
      'sl': { flag: '🇸🇮', native: 'Slovenščina', english: 'Slovenian' },
      'sr': { flag: '🇷🇸', native: 'Српски', english: 'Serbian' },
      'lt': { flag: '🇱🇹', native: 'Lietuvių', english: 'Lithuanian' },
      'lv': { flag: '🇱🇻', native: 'Latviešu', english: 'Latvian' },
      'et': { flag: '🇪🇪', native: 'Eesti', english: 'Estonian' },
      'vi': { flag: '🇻🇳', native: 'Tiếng Việt', english: 'Vietnamese' },
      'th': { flag: '🇹🇭', native: 'ไทย', english: 'Thai' },
      'id': { flag: '🇮🇩', native: 'Bahasa Indonesia', english: 'Indonesian' },
      'ms': { flag: '🇲🇾', native: 'Bahasa Melayu', english: 'Malay' },
      'hi': { flag: '🇮🇳', native: 'हिन्दी', english: 'Hindi' },
      'bn': { flag: '🇧🇩', native: 'বাংলা', english: 'Bengali' },
      'fa': { flag: '🇮🇷', native: 'فارسی', english: 'Persian' },
      'he': { flag: '🇮🇱', native: 'עברית', english: 'Hebrew' },
      'ur': { flag: '🇵🇰', native: 'اردو', english: 'Urdu' },
      'sw': { flag: '🇰🇪', native: 'Kiswahili', english: 'Swahili' },
      'am': { flag: '🇪🇹', native: 'አማርኛ', english: 'Amharic' },
    };

    const handleLanguageClick = async (langCode: string) => {
      setSelectedLanguage(langCode);
      setLoading(true);
      setError(null);

      try {
        await CustomerService.activateSession(sessionId, langCode);

        // Load message history
        try {
          const history = await MessageService.getMessages(sessionId);
          history.forEach((msg) => addMessage(msg));
        } catch (historyErr) {
          console.warn('Failed to load message history:', historyErr);
        }

        startSession(sessionId, 'customer', langCode);
        setViewMode('active');
      } catch (err) {
        console.error('Failed to activate session:', err);
        setError('Fehler beim Beitreten zur Session. Bitte versuchen Sie es erneut.');
        setLoading(false);
      }
    };

    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Header />
        <div className="flex-1 flex items-center justify-center px-4 py-12 sm:py-20">
        <div className="bg-white rounded-card-lg shadow-card p-8 sm:p-12 w-full max-w-2xl">
          <div className="flex items-center justify-between mb-8">
            <h1 className="text-2xl sm:text-3xl font-bold text-text leading-tight">Sprache auswählen</h1>
            <button
              onClick={() => setViewMode('input')}
              className="text-primary hover:text-primary-dark font-semibold text-base sm:text-lg transition-colors"
            >
              Zurück
            </button>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-card text-red-800">
              {error}
            </div>
          )}

          <div className="mb-8 p-6 bg-primary/10 border border-primary/20 rounded-card">
            <div className="text-sm text-gray-600 font-semibold mb-2">Session-ID:</div>
            <div className="text-lg sm:text-xl font-mono font-bold text-primary-dark break-all">{sessionId}</div>
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4"></div>
              <p className="text-gray-600 text-lg">Beitritt läuft...</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:gap-6">
              {languages.map((lang) => {
                const langInfo = languageFlags[lang.code] || {
                  flag: '🏳️',
                  native: lang.native_name || lang.name,
                  english: lang.name,
                };

                return (
                  <button
                    key={lang.code}
                    onClick={() => handleLanguageClick(lang.code)}
                    className="flex flex-col items-center p-4 sm:p-6 border-2 border-gray-200 rounded-card hover:border-primary hover:bg-primary/5 transition-all duration-200 active:scale-95"
                  >
                    <div className="text-4xl sm:text-5xl mb-3">{langInfo.flag}</div>
                    <div className="text-center">
                      <div className="font-semibold text-text text-sm sm:text-base">
                        {langInfo.native}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">
                        {langInfo.english}
                      </div>
                    </div>
                  </button>
                );
          })}
        </div>
      )}
    </div>
    </div>
    <Footer />
  </div>
);
}

  // Active session view
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 flex flex-col w-full">
        <div className="bg-white shadow-card">
          <div className="w-full px-4 sm:px-6 lg:px-8 py-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex-1 min-w-0">
                <h1 className="text-2xl sm:text-3xl font-bold text-text leading-tight">Session aktiv</h1>
                <div className="text-sm sm:text-base mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
                  <span className="text-gray-600 font-semibold">Session:</span>
                  <span className="font-mono font-bold text-primary-dark break-all">{sessionId}</span>
                  <span className="text-gray-400">•</span>
                  <span className="text-gray-600 font-semibold">Sprache:</span>
                  <span className="font-semibold text-text">{languages.find(l => l.code === selectedLanguage)?.name || selectedLanguage}</span>
                </div>
              </div>
              <ConnectionStatusIndicator />
            </div>
          </div>
        </div>

        <div className="flex-1 bg-white flex flex-col" style={{ height: 'calc(100vh - 200px)', minHeight: '400px' }}>
          <MessageList showMetadata={true} />
          <MessageInput disabled={!isActive} />
        </div>
      </div>
      <Footer />
    </div>
  );
}
