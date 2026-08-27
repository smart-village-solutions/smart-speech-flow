import { Navigate, Route, Routes, useParams } from 'react-router-dom';
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

/** QR deep link: /join/:sessionId lands straight on the language picker. */
function JoinRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>();
  return <Navigate to={`/s/${sessionId}/language`} replace />;
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

      {/* Legacy surface, unstyled, kept working until admin designs exist.
          SessionProvider is mounted per route rather than at the root: only
          these two pages consume it. */}
      <Route path="/legacy" element={<LandingPage />} />
      <Route
        path="/admin"
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
