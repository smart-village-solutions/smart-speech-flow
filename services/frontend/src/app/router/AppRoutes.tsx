import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { RequireSession } from './RequireSession';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import { SessionProvider } from '@/contexts/SessionContext';
import LandingPage from '@/pages/LandingPage';
import AdminPage from '@/pages/AdminPage';
import CustomerPage from '@/pages/CustomerPage';
import NotFoundPage from '@/pages/NotFoundPage';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useServices } from '@/app/providers/services';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import { logoutFromKeycloak, requireKeycloakLogin } from '@/app/auth/keycloak';
import { AdminLoginScreen } from '@/features/admin/AdminLoginScreen';
import { useAdminAuth } from '@/features/admin/useAdminAuth';

/** QR deep link: /join/:sessionId lands straight on the language picker. */
function JoinRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>();
  return <Navigate to={`/s/${sessionId}/language`} replace />;
}

/** Keycloak-protected administrative entrypoint. */
function LoginEntry() {
  const { config } = useServices();
  const [authenticated, setAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    void requireKeycloakLogin(config).then((value) => {
      setAuthenticated(value);
      setReady(true);
    });
  }, [config]);

  const leave = () => setSessionId(null);

  // Return to the public entry after Keycloak sign-out.
  const out = () => {
    setSessionId(null);
    void logoutFromKeycloak();
    void navigate('/');
  };

  if (!ready || !authenticated) return null;

  if (sessionId === null) {
    return <AdminDashboardScreen onEnterSession={setSessionId} onSignOut={out} />;
  }

  return <AdminSessionScreen sessionId={sessionId} onLeave={leave} onSignOut={out} />;
}

function LegacyAdminEntry() {
  const { signedIn, signIn, signOut } = useAdminAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const navigate = useNavigate();
  const out = () => {
    setSessionId(null);
    signOut();
    void navigate('/');
  };

  if (!signedIn) return <AdminLoginScreen onSignIn={signIn} onBack={out} />;
  if (sessionId === null) {
    return <AdminDashboardScreen onEnterSession={setSessionId} onSignOut={out} />;
  }
  return <AdminSessionScreen sessionId={sessionId} onLeave={() => setSessionId(null)} onSignOut={out} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<AccessCodeScreen />} />
      <Route path="/join/:sessionId" element={<JoinRedirect />} />

      <Route path="/s/:sessionId" element={<RequireSession />}>
        <Route path="language" element={<LanguageSelectScreen />} />
        <Route path="info/:languageCode" element={<ConsentScreen />} />
        <Route path="live" element={<ConversationScreen />} />
      </Route>

      <Route path="/login" element={<LoginEntry />} />
      <Route path="/admin" element={<LegacyAdminEntry />} />

      {/* Legacy surfaces, unstyled, kept reachable rather than deleted.
          SessionProvider is mounted per route rather than at the root: only
          these two pages consume it. */}
      <Route path="/legacy" element={<LandingPage />} />
      <Route
        path="/legacy/admin"
        element={
          <ProtectedRoute>
            <SessionProvider>
              <AdminPage />
            </SessionProvider>
          </ProtectedRoute>
        }
      />
      <Route
        path="/customer"
        element={
          <ProtectedRoute>
            <SessionProvider>
              <CustomerPage />
            </SessionProvider>
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
