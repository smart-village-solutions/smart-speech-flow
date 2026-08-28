import { useState } from 'react';
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
import { AdminLoginScreen } from '@/features/admin/AdminLoginScreen';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import { useAdminAuth } from '@/features/admin/useAdminAuth';

/** QR deep link: /join/:sessionId lands straight on the language picker. */
function JoinRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>();
  return <Navigate to={`/s/${sessionId}/language`} replace />;
}

/**
 * The admin entry. `skipLogin` is the development flag's only remaining job:
 * with a password on /admin, a second path showing the same login would add
 * nothing, so it jumps straight to the dashboard instead.
 *
 * Signing out drops the open session as well as the password: leaving one
 * behind a login screen would resume it on the next sign-in without asking.
 */
function AdminEntry({ skipLogin = false }: Readonly<{ skipLogin?: boolean }>) {
  const { signedIn, signIn, signOut } = useAdminAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const navigate = useNavigate();

  const leave = () => setSessionId(null);

  // Leaving for `/` rather than falling through to the login is what makes this
  // a sign-out on every route. `/admin/dev` skips the login, so without it the
  // dashboard simply re-rendered and nothing appeared to happen.
  const out = () => {
    setSessionId(null);
    signOut();
    void navigate('/');
  };

  if (!skipLogin && !signedIn) {
    return <AdminLoginScreen onSignIn={signIn} onBack={out} />;
  }

  if (sessionId === null) {
    return <AdminDashboardScreen onEnterSession={setSessionId} onSignOut={out} />;
  }

  return <AdminSessionScreen sessionId={sessionId} onLeave={leave} onSignOut={out} />;
}

export function AppRoutes() {
  const { config } = useServices();

  return (
    <Routes>
      <Route path="/" element={<AccessCodeScreen />} />
      <Route path="/join/:sessionId" element={<JoinRedirect />} />

      <Route path="/s/:sessionId" element={<RequireSession />}>
        <Route path="language" element={<LanguageSelectScreen />} />
        <Route path="info/:languageCode" element={<ConsentScreen />} />
        <Route path="live" element={<ConversationScreen />} />
      </Route>

      <Route path="/admin" element={<AdminEntry />} />
      {config.adminDevEntry && <Route path="/admin/dev" element={<AdminEntry skipLogin />} />}

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
