import { useNavigate } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { useStaffCopy } from '@/features/content/useStaffCopy';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { RichText } from '@/ui/patterns/RichText';
import { SystemLoadCard } from './SystemLoadCard';
import { AdminNewSessionButton } from './AdminNewSessionButton';
import type { ReactNode } from 'react';
import { ConversationUsageCard } from './ConversationUsageCard';
import { useOwnLiveSessionId } from './useAdminSessions';

interface AdminDashboardScreenProps {
  onEnterSession: (sessionId: string) => void;
  onSignOut: () => void;
  onOpenKeys?: () => void;
  children?: ReactNode;
  navigation?: ReactNode;
  conversationView?: boolean;
  accountUrl?: string;
  studioUrl?: string;
}

export function AdminDashboardScreen({
  onEnterSession,
  onSignOut,
  onOpenKeys,
  children,
  navigation,
  conversationView = true,
  accountUrl,
  studioUrl,
}: Readonly<AdminDashboardScreenProps>) {
  const copy = useStaffCopy();
  const { openFeedback } = useFeedback();
  const navigate = useNavigate();

  const { data: ownLiveSessionId = null } = useOwnLiveSessionId();
  useScreenLocale('de');

  return (
    <ScreenShell>
      <AdminHeader
        onBack={() => navigate(-1)}
        onHome={() => void navigate('/')}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
        onOpenKeys={onOpenKeys}
      />

      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        {navigation}
        {conversationView && (
          <>
            <div className="flex flex-col gap-4 md:flex-row">
              <div className="rounded-2xl border border-border-card bg-surface-card p-5 md:basis-2/3">
                <p className="mb-1.5 text-thanks font-semibold text-fg-strong">{copy.headline}</p>
                <div className="flex flex-col gap-2 text-note leading-chat text-fg-muted">
                  <RichText html={copy.introHtml} />
                </div>
              </div>

              <SystemLoadCard copy={copy.load} />
            </div>

            <AdminNewSessionButton
              liveSessionId={ownLiveSessionId}
              callToAction={copy.callToAction}
              invite={copy.invite}
              onEnter={onEnterSession}
            />
          </>
        )}
        {children}
        {conversationView && <ConversationUsageCard />}
      </div>
      <SiteLegalLinks className="mt-auto px-5 pt-4 pb-legal-end" />
    </ScreenShell>
  );
}
