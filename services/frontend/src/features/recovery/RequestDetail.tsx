import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { RequestProgress } from '@/domain/recovery/requests.types';
import { formatDate } from '@/features/archive/format';
import { Button } from '@/ui/primitives/Button';
import { CombineResult } from './CombineResult';
import { DecisionList } from './DecisionList';
import { RecoveryLocked } from './RecoveryLocked';
import { StatusChip } from './StatusChip';
import { validApprovals } from './steps';
import { useCancel, useCombine, useRequestProgress } from './useRecovery';

function Facts({ progress }: Readonly<{ progress: RequestProgress }>) {
  const { t, i18n } = useTranslation();
  const rows: [string, ReactNode][] = [
    ['status', <StatusChip key="s" status={progress.status} />],
    ['created', formatDate(progress.createdAt, i18n.language)],
    ['expires', formatDate(progress.expiresAt, i18n.language)],
    ['conversations', progress.conversations],
    [
      'reason',
      <span key="r" className="whitespace-pre-wrap">
        {progress.reason}
      </span>,
    ],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-label">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-fg-muted">{t(`admin.recovery.detail.${term}`)}</dt>
          <dd className="text-fg-body">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface RequestDetailProps {
  requestId: string;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
  onCancelled: () => void;
}

export function RequestDetail({
  requestId,
  keys,
  onOpenKeys,
  onCancelled,
}: Readonly<RequestDetailProps>) {
  const { t } = useTranslation();
  const progress = useRequestProgress(requestId);
  const combine = useCombine(requestId, keys);
  if (progress.isPending) return null;
  if (progress.isError)
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.recovery.unavailable')}
      </p>
    );
  const found = progress.data;
  const valid = validApprovals(found);
  const open = found.status === 'open';

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
        <h2 className="text-thanks font-semibold text-fg-strong">
          {t('admin.recovery.detail.title')}
        </h2>
        <Facts progress={found} />
      </div>
      <p className="text-body font-semibold text-fg-strong">
        {t('admin.recovery.detail.progress', { valid, k: found.k })}
      </p>
      <h3 className="text-note font-semibold text-fg-strong">
        {t('admin.recovery.detail.decisions')}
      </h3>
      <DecisionList decisions={found.decisions} />
      {open && valid >= found.k && keys === null && <RecoveryLocked onOpenKeys={onOpenKeys} />}
      {open && valid >= found.k && keys !== null && (
        <Button
          className="self-start bg-accent text-accent-on"
          disabled={combine.pending}
          onClick={() => void combine.run()}
        >
          {t(combine.pending ? 'admin.recovery.detail.combining' : 'admin.recovery.detail.combine')}
        </Button>
      )}
      {combine.outcome !== null && (
        <CombineResult outcome={combine.outcome} decisions={found.decisions} />
      )}
      {open && <CancelButton requestId={requestId} onCancelled={onCancelled} />}
    </section>
  );
}

function CancelButton({
  requestId,
  onCancelled,
}: Readonly<{ requestId: string; onCancelled: () => void }>) {
  const { t } = useTranslation();
  const cancelling = useCancel(requestId);
  const cancel = async () => {
    if (await cancelling.cancel()) onCancelled();
  };
  return (
    <button
      type="button"
      className="self-start text-label font-medium text-fg-danger"
      disabled={cancelling.pending}
      onClick={() => void cancel()}
    >
      {t('admin.recovery.detail.cancel')}
    </button>
  );
}
