import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useBrand } from '@/app/providers/brand';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { isReenterable } from '@/domain/admin/admin.types';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { SystemLoadCard } from './SystemLoadCard';
import { AdminNewSessionButton } from './AdminNewSessionButton';
import { AdminSessionList } from './AdminSessionList';
import { useAdminSessions } from './useAdminSessions';

interface AdminDashboardScreenProps {
  onEnterSession: (sessionId: string) => void;
  onSignOut: () => void;
}

export function AdminDashboardScreen({
  onEnterSession,
  onSignOut,
}: Readonly<AdminDashboardScreenProps>) {
  const { t } = useTranslation();
  const { brand } = useBrand();
  const { openFeedback } = useFeedback();
  const navigate = useNavigate();
  const { data: sessions = [], isError } = useAdminSessions();
  useScreenLocale('de');

  // The gateway allows one live session, so the first re-enterable row is the
  // one creating another would terminate.
  const live = sessions.find(isReenterable) ?? null;

  return (
    <ScreenShell>
      <AdminHeader
        onBack={() => navigate(-1)}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
        onSignOut={onSignOut}
      />

      <div className="flex flex-col gap-6 px-5 pb-16 pt-24">
        <div className="flex gap-4">
          <div className="basis-2/3 rounded-2xl border border-border-card bg-surface-card p-5">
            <p className="mb-1.5 text-thanks font-semibold text-fg-strong">
              {t(`admin.dashboard.welcome.${brand}`)}
            </p>
            <p className="text-note leading-chat text-fg-muted">{t('admin.dashboard.intro')}</p>
          </div>

          <SystemLoadCard />
        </div>

        <AdminNewSessionButton liveSessionId={live?.id ?? null} onEnter={onEnterSession} />

        <AdminSessionList sessions={sessions} isError={isError} onEnter={onEnterSession} />
      </div>
    </ScreenShell>
  );
}
