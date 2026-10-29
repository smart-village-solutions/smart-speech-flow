import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { ApprovalReview } from './ApprovalReview';
import { faultKey } from './faults';
import type { StaffScreenProps } from './RecoveryRequestsScreen';
import { SummaryList } from './SummaryList';
import { useApprovalDetail, useApprovalsList } from './useRecovery';
import { faultOf } from './steps';

function Approvals({ onOpen }: Readonly<{ onOpen: (id: string) => void }>) {
  const { t } = useTranslation();
  const list = useApprovalsList();
  if (list.isError)
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.recovery.unavailable')}
      </p>
    );
  if (!list.data) return null;
  return (
    <SummaryList
      rows={list.data}
      empty={t('admin.recovery.approvals.empty')}
      showRequester
      onOpen={onOpen}
    />
  );
}

interface ReviewProps {
  requestId: string;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
  onDone: () => void;
}

function Review({ requestId, keys, onOpenKeys, onDone }: Readonly<ReviewProps>) {
  const { t } = useTranslation();
  const detail = useApprovalDetail(requestId);
  if (detail.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t(faultKey(faultOf(detail.error)))}
      </p>
    );
  }
  if (!detail.data) return null;
  return (
    <ApprovalReview
      detail={detail.data}
      keys={keys}
      onOpenKeys={onOpenKeys}
      onDecided={onDone}
      onRetry={() => void detail.refetch()}
    />
  );
}

/** Requests a custodian may decide on (spec §9.5); never the custodian's own. */
export function RecoveryApprovalsScreen({
  onBack,
  onOpenKeys,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<StaffScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const unlocked = useUnlockedKeys();
  const [open, setOpen] = useState<string | null>(null);
  useScreenLocale('de');

  return (
    <ScreenShell>
      <AdminHeader
        onBack={open === null ? onBack : () => setOpen(null)}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">
            {t('admin.recovery.approvals.title')}
          </h1>
          <p className="text-note leading-chat text-fg-muted">
            {t('admin.recovery.approvals.intro')}
          </p>
        </div>
        {open === null && <Approvals onOpen={setOpen} />}
        {open !== null && (
          <Review
            key={open}
            requestId={open}
            keys={unlocked}
            onOpenKeys={onOpenKeys}
            onDone={() => setOpen(null)}
          />
        )}
      </div>
    </ScreenShell>
  );
}
