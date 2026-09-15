import { useEffect, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { RequireSession } from './RequireSession';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import { SessionProvider } from '@/contexts/SessionContext';
import CustomerPage from '@/pages/CustomerPage';
import NotFoundPage from '@/pages/NotFoundPage';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useServices } from '@/app/providers/services';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import {
  logoutFromKeycloak,
  requireKeycloakLogin,
  subscribeToKeycloakExpiration,
} from '@/app/auth/keycloak';
import { AdminLoginScreen } from '@/features/admin/AdminLoginScreen';
import { useAdminAuth } from '@/features/admin/useAdminAuth';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';

/** QR deep link: /join/:sessionId lands straight on the language picker. */
function JoinRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>();
  return <Navigate to={`/s/${sessionId}/language`} replace />;
}

function TenantLoginEntry() {
  const { tenantId = '' } = useParams<{ tenantId: string }>();
  return (
    <AdminQueryBoundary key={tenantId}>
      <TenantLoginSession tenantId={tenantId} />
    </AdminQueryBoundary>
  );
}

/** Each administrative entry owns its entire query cache, including session queries. */
function AdminQueryBoundary({ children }: { children: ReactNode }) {
  const parent = useQueryClient();
  const [client] = useState(() => new QueryClient({ defaultOptions: parent.getDefaultOptions() }));
  useEffect(
    () => () => {
      client.clear();
    },
    [client]
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Resolve the route ID through the validated directory before using a realm. */
function TenantLoginSession({ tenantId }: { tenantId: string }) {
  const { config, loginTenant } = useServices();
  const { t } = useTranslation();
  const [status, setStatus] = useState<'loading' | 'authenticated' | 'missing' | 'error'>(
    'loading'
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(
    () =>
      subscribeToKeycloakExpiration(() => {
        void navigate('/login', { replace: true });
      }),
    [navigate]
  );

  useEffect(() => {
    let cancelled = false;
    void loginTenant
      .list()
      .then(async (tenants) => {
        if (cancelled) return;
        const tenant = tenants.find((entry) => entry.id === tenantId);
        if (!tenant) {
          setStatus('missing');
          return;
        }
        const authenticated = await requireKeycloakLogin(config, tenant);
        if (!cancelled && authenticated) setStatus('authenticated');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [config, loginTenant, tenantId]);

  const leave = () => setSessionId(null);

  const out = () => {
    setSessionId(null);
    void logoutFromKeycloak().catch(() => {
      /* The local session is already cleared. */
    });
    void navigate('/login');
  };

  if (status === 'missing') return <NotFoundPage />;
  if (status === 'error') return <p role="alert">{t('admin.tenantLogin.unavailable')}</p>;
  if (status !== 'authenticated') return null;

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
  return (
    <AdminSessionScreen sessionId={sessionId} onLeave={() => setSessionId(null)} onSignOut={out} />
  );
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

      <Route path="/login" element={<TenantLoginScreen />} />
      <Route path="/login/:tenantId" element={<TenantLoginEntry />} />
      <Route
        path="/admin"
        element={
          <AdminQueryBoundary>
            <LegacyAdminEntry />
          </AdminQueryBoundary>
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
