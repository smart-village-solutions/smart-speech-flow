import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { RequireSession } from './RequireSession';
import { RouteState } from './RouteState';
import { FeedbackProvider } from '@/app/providers/FeedbackProvider';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import NotFoundPage from '@/pages/NotFoundPage';
import { useServices } from '@/app/providers/services';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import {
  logoutFromKeycloak,
  getAccountConsoleUrl,
  getStudioAdministrationUrl,
  requireKeycloakLogin,
  subscribeToKeycloakExpiration,
  subscribeToKeycloakAuthorization,
} from '@/app/auth/keycloak';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';
import { contentKeys } from '@/features/content/contentQuery';

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

/**
 * Each administrative entry owns its entire query cache, including session
 * queries. Installation content is the one exception: it is anonymous and the
 * same for every tenant, so the entry starts with the copy the app holds.
 * The entry's own feedback sheet reads the staff form from this cache too;
 * the app-wide sheet would fetch tenant texts into the shared one.
 */
function AdminQueryBoundary({ children }: Readonly<{ children: ReactNode }>) {
  const parent = useQueryClient();
  const [client] = useState(() => {
    const own = new QueryClient({ defaultOptions: parent.getDefaultOptions() });
    const installation = parent.getQueryState(contentKeys.public);
    if (installation?.data !== undefined) {
      own.setQueryData(contentKeys.public, installation.data, {
        updatedAt: installation.dataUpdatedAt,
      });
    }
    return own;
  });
  useEffect(
    () => () => {
      client.clear();
    },
    [client]
  );
  return (
    <QueryClientProvider client={client}>
      <FeedbackProvider>{children}</FeedbackProvider>
    </QueryClientProvider>
  );
}

/** Resolve the route ID through the validated directory before using a realm. */
function TenantLoginSession({ tenantId }: Readonly<{ tenantId: string }>) {
  const { config, loginTenant } = useServices();
  const { t } = useTranslation();
  const [status, setStatus] = useState<'loading' | 'authenticated' | 'missing' | 'error'>(
    'loading'
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const studioUrl = useSyncExternalStore(
    subscribeToKeycloakAuthorization,
    () => getStudioAdministrationUrl(tenantId),
    () => null
  );
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
  if (status === 'error')
    return (
      <RouteState>
        <p role="alert" className="text-center text-note text-fg-muted">
          {t('admin.tenantLogin.unavailable')}
        </p>
      </RouteState>
    );
  if (status !== 'authenticated') return <RouteState />;

  const accountUrl = getAccountConsoleUrl() ?? undefined;

  if (sessionId === null) {
    return (
      <AdminDashboardScreen
        onEnterSession={setSessionId}
        onSignOut={out}
        accountUrl={accountUrl}
        studioUrl={studioUrl ?? undefined}
      />
    );
  }

  return (
    <AdminSessionScreen
      sessionId={sessionId}
      onLeave={leave}
      onSignOut={out}
      accountUrl={accountUrl}
      studioUrl={studioUrl ?? undefined}
    />
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
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
