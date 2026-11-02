import type { ReactNode } from 'react';
import { useFeedback } from '@/app/providers/feedback';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';

interface StaffViewShellProps {
  onBack: () => void;
  /** Set while one item is open: back closes it before leaving the view. */
  onClose?: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
  children: ReactNode;
}

/** The archive's and the reviews' frame: admin header, then one column of cards. */
export function StaffViewShell({
  onBack,
  onClose,
  onSignOut,
  accountUrl,
  studioUrl,
  children,
}: Readonly<StaffViewShellProps>) {
  const { openFeedback } = useFeedback();
  return (
    <ScreenShell>
      <AdminHeader
        onBack={onClose ?? onBack}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">{children}</div>
    </ScreenShell>
  );
}
