import { useTranslation } from 'react-i18next';
import type { RecoveryKey } from '@/domain/recovery/recovery.types';
import { Button } from '@/ui/primitives/Button';

const MODE = { standard: 'admin.ceremony.modeStandard', enhanced: 'admin.ceremony.modeEnhanced' } as const;

/** The tenant's active recovery key; recording may be enabled from here on (spec §9.2). */
interface RecoveryKeyCardProps {
  recoveryKey: RecoveryKey;
  /** Offered to an org admin while no ceremony runs (spec §9.7). */
  onReshare?: () => void;
}

export function RecoveryKeyCard({ recoveryKey, onReshare }: Readonly<RecoveryKeyCardProps>) {
  const { t } = useTranslation();

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.ceremony.keyActiveTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.ceremony.keyActiveBody', { k: recoveryKey.k, n: recoveryKey.n })} {t(MODE[recoveryKey.mode])}
      </p>
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.ceremony.transcriptLabel')} <code>{recoveryKey.transcriptDisplay}</code>
      </p>
      {recoveryKey.usableShares !== null && (
        // One stale custodian more and a resharing would have to wait for the paper shares (§9.6).
        <p className={`text-label ${recoveryKey.usableShares > recoveryKey.k ? 'text-fg-muted' : 'text-fg-status-alert'}`}>
          {t('admin.ceremony.usableShares', { usable: recoveryKey.usableShares, k: recoveryKey.k })}
        </p>
      )}
      {recoveryKey.previousHadPaper && (
        <p role="alert" className="text-note text-fg-status-alert">
          {t('admin.ceremony.reshare.voidSheets')}
        </p>
      )}
      {onReshare !== undefined && (
        <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={onReshare}>
          {t('admin.ceremony.reshare.start')}
        </Button>
      )}
    </section>
  );
}
