import { useTranslation } from 'react-i18next';
import type { RecoveryDecision } from '@/domain/recovery/requests.types';
import { faultKey } from './faults';
import type { CombineOutcome } from './steps';

interface CombineResultProps {
  outcome: CombineOutcome;
  decisions: readonly RecoveryDecision[];
}

/** What combining did; a rejection names the custodian whose partial failed its proof. */
export function CombineResult({ outcome, decisions }: Readonly<CombineResultProps>) {
  const { t } = useTranslation();
  const done = outcome.kind === 'done';
  const nameOf = (index: number) => {
    const decision = decisions.find((d) => d.holderIndex === index);
    return decision?.custodianName ?? decision?.custodianSub ?? String(index);
  };
  return (
    <div
      role={done ? 'status' : 'alert'}
      className="flex flex-col gap-1.5 rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <p className={`text-note ${done ? 'text-fg-status' : 'text-fg-status-alert'}`}>
        {t(`admin.recovery.combine.${outcome.kind}`)}
      </p>
      {outcome.kind === 'done' && outcome.unrecoverable > 0 && (
        <p className="text-label text-fg-status-alert">
          {t('admin.keyRecovery.unrecoverable', { count: outcome.unrecoverable })}
        </p>
      )}
      {outcome.kind === 'failed' && (
        <p className="text-label text-fg-status-alert">{t(faultKey(outcome.code))}</p>
      )}
      {outcome.kind === 'waiting' &&
        outcome.rejected.map((index) => (
          <p key={index} className="text-label text-fg-status-alert">
            {t('admin.recovery.combine.rejectedCustodian', { name: nameOf(index) })}
          </p>
        ))}
    </div>
  );
}
