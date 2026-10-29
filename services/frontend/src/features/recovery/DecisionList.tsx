import { useTranslation } from 'react-i18next';
import type { RecoveryDecision } from '@/domain/recovery/requests.types';
import { formatDate } from '@/features/archive/format';
import { Chip } from './StatusChip';

/** Each custodian's decision; a rejected approval says so, and the custodian may approve again. */
export function DecisionList({ decisions }: Readonly<{ decisions: readonly RecoveryDecision[] }>) {
  const { t, i18n } = useTranslation();
  if (decisions.length === 0)
    return <p className="text-note text-fg-muted">{t('admin.recovery.detail.noDecisions')}</p>;
  return (
    <ul className="divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card">
      {decisions.map((d) => (
        <li key={`${d.holderIndex}:${d.attempt}`} className="flex flex-col gap-1 px-4 py-3">
          <span className="flex items-center gap-3">
            <span className="flex-1 text-note font-semibold text-fg-strong">
              {d.custodianName ?? d.custodianSub}
            </span>
            <span className="text-label text-fg-muted">
              {formatDate(d.decidedAt, i18n.language)}
            </span>
            <Chip
              label={t(`admin.recovery.decision.${d.decision}`)}
              tone={d.decision === 'approved' ? 'status' : 'muted'}
            />
            {d.rejected && <Chip label={t('admin.recovery.decision.rejected')} tone="alert" />}
          </span>
          {d.reason !== null && <span className="text-label text-fg-muted">{d.reason}</span>}
        </li>
      ))}
    </ul>
  );
}
