import type { ReactNode } from 'react';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';

interface RecoveryShellProps {
  /** Back within the screen, or out of it when nothing is open. */
  onBack: () => void;
  onHome: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
  title: string;
  intro: string;
  children: ReactNode;
}

/** The staff header and intro card every recovery screen opens with. */
export function RecoveryShell({
  onBack,
  onHome,
  onSignOut,
  accountUrl,
  studioUrl,
  title,
  intro,
  children,
}: Readonly<RecoveryShellProps>) {
  const { openFeedback } = useFeedback();
  useScreenLocale('de');
  return (
    <ScreenShell>
      <AdminHeader
        onBack={onBack}
        onHome={onHome}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">{title}</h1>
          <p className="text-note leading-chat text-fg-muted">{intro}</p>
        </div>
        {children}
      </div>
    </ScreenShell>
  );
}
