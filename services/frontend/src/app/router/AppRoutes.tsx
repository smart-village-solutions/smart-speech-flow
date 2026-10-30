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
import { ArchiveScreen } from '@/features/archive/ArchiveScreen';
import { ARCHIVE_PERMISSIONS, ARCHIVE_VIEW } from '@/features/archive/useArchive';
import { CeremonyScreen } from '@/features/ceremony/CeremonyScreen';
import { CEREMONY_VIEW, CUSTODIAN, TENANT_MANAGE } from '@/features/ceremony/useCeremony';
import { KeysScreen } from '@/features/keys/KeysScreen';
import { KEYS_VIEW } from '@/features/keys/useKeys';
import { KeyRecoveryScreen } from '@/features/recovery/KeyRecoveryScreen';
import { RecoveryApprovalsScreen } from '@/features/recovery/RecoveryApprovalsScreen';
import { RecoveryRequestsScreen } from '@/features/recovery/RecoveryRequestsScreen';
import { KEY_RECOVERY_VIEW } from '@/features/recovery/useKeyRecovery';
import {
  RECOVERY_APPROVALS_VIEW,
  RECOVERY_REQUESTS_VIEW,
  SUPERVISE,
} from '@/features/recovery/useRecovery';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import {
  logoutFromKeycloak,
  getAccountConsoleUrl,
  getStudioAdministrationUrl,
  hasPermission,
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

interface StaffScreensProps {
  onSignOut: () => void;
  studioUrl?: string;
}

/** Staff screens that share one shape: back to the dashboard, keys on the way. */
const STAFF_SCREENS = {
  [CEREMONY_VIEW]: CeremonyScreen,
  [ARCHIVE_VIEW]: ArchiveScreen,
  [KEY_RECOVERY_VIEW]: KeyRecoveryScreen,
  [RECOVERY_REQUESTS_VIEW]: RecoveryRequestsScreen,
  [RECOVERY_APPROVALS_VIEW]: RecoveryApprovalsScreen,
} as const;
type StaffView = 'dashboard' | typeof KEYS_VIEW | keyof typeof STAFF_SCREENS;
const RESUMABLE: ReadonlySet<string> = new Set([KEYS_VIEW, ...Object.keys(STAFF_SCREENS)]);

/** A step-up redirect reloads the app; it asked to come back to the view it left. */
function resumedView(remembered: string | null): StaffView {
  return remembered !== null && RESUMABLE.has(remembered)
    ? (remembered as StaffView)
    : 'dashboard';
}

/** Which staff screens the menu offers: a navigation hint, the gateway checks each itself. */
const OFFERED: Record<keyof typeof STAFF_SCREENS, () => boolean> = {
  [CEREMONY_VIEW]: () => hasPermission(TENANT_MANAGE) || hasPermission(CUSTODIAN),
  [ARCHIVE_VIEW]: () => ARCHIVE_PERMISSIONS.some((permission) => hasPermission(permission)),
  [KEY_RECOVERY_VIEW]: () => ARCHIVE_PERMISSIONS.some((permission) => hasPermission(permission)),
  [RECOVERY_REQUESTS_VIEW]: () => hasPermission(SUPERVISE),
  [RECOVERY_APPROVALS_VIEW]: () => hasPermission(CUSTODIAN),
};

function opener(view: keyof typeof STAFF_SCREENS, setView: (view: StaffView) => void) {
  return OFFERED[view]() ? () => setView(view) : undefined;
}

/** The signed-in staff screens; switched by state, since Keycloak returns to one URL. */
function StaffScreens({ onSignOut, studioUrl }: Readonly<StaffScreensProps>) {
  const { resume } = useServices();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [view, setView] = useState<StaffView>(() => resumedView(resume.take()));
  // A custodian sent from the ceremony to unlock their keys goes back to the ceremony.
  const [keysReturn, setKeysReturn] = useState<StaffView>('dashboard');
  const accountUrl = getAccountConsoleUrl() ?? undefined;
  const out = () => {
    setSessionId(null);
    onSignOut();
  };
  const openKeys = (from: StaffView) => {
    setKeysReturn(from);
    setView(KEYS_VIEW);
  };
  const shared = {
    onSignOut: out,
    accountUrl,
    studioUrl,
    onOpenKeyRecovery: opener(KEY_RECOVERY_VIEW, setView),
  };

  if (view === KEYS_VIEW) return <KeysScreen onBack={() => setView(keysReturn)} {...shared} />;
  if (view !== 'dashboard') {
    const Screen = STAFF_SCREENS[view];
    return <Screen onBack={() => setView('dashboard')} onOpenKeys={() => openKeys(view)} {...shared} />;
  }
  if (sessionId === null) {
    return (
      <AdminDashboardScreen
        onEnterSession={setSessionId}
        onOpenKeys={() => openKeys('dashboard')}
        onOpenCeremony={opener(CEREMONY_VIEW, setView)}
        onOpenArchive={opener(ARCHIVE_VIEW, setView)}
        onOpenRecoveryRequests={opener(RECOVERY_REQUESTS_VIEW, setView)}
        onOpenRecoveryApprovals={opener(RECOVERY_APPROVALS_VIEW, setView)}
        {...shared}
      />
    );
  }

  return <AdminSessionScreen sessionId={sessionId} onLeave={() => setSessionId(null)} {...shared} />;
}

/** Resolve the route ID through the validated directory before using a realm. */
function TenantLoginSession({ tenantId }: Readonly<{ tenantId: string }>) {
  const { config, loginTenant, keyVault } = useServices();
  const { t } = useTranslation();
  const [status, setStatus] = useState<'loading' | 'authenticated' | 'missing' | 'error'>(
    'loading'
  );
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

  const out = () => {
    keyVault.lock();
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

  return <StaffScreens onSignOut={out} studioUrl={studioUrl ?? undefined} />;
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
