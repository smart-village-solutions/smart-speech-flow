import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { ApprovalReview } from './ApprovalReview';
import { faultKey } from './faults';
import type { StaffScreenProps } from './RecoveryRequestsScreen';
import { RecoveryShell } from './RecoveryShell';
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
  // A share sealed to an earlier key opens nothing; resharing brings it back (§9.6).
  if (list.data.shareStale)
    return (
      <p
        role="alert"
        className="rounded-2xl border border-border-status bg-surface-card p-5 text-note text-fg-status-alert"
      >
        {t('admin.recovery.error.SHARE_STALE')}
      </p>
    );
  return (
    <SummaryList
      rows={list.data.requests}
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
  const unlocked = useUnlockedKeys();
  const [open, setOpen] = useState<string | null>(null);

  return (
    <RecoveryShell
      onBack={open === null ? onBack : () => setOpen(null)}
      onHome={onBack}
      onSignOut={onSignOut}
      accountUrl={accountUrl}
      studioUrl={studioUrl}
      title={t('admin.recovery.approvals.title')}
      intro={t('admin.recovery.approvals.intro')}
    >
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
    </RecoveryShell>
  );
}
