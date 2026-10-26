import { useTranslation } from 'react-i18next';
import type { RecoveryKey } from '@/domain/recovery/recovery.types';

const MODE = { standard: 'admin.ceremony.modeStandard', enhanced: 'admin.ceremony.modeEnhanced' } as const;

/** The tenant's active recovery key; recording may be enabled from here on (spec §9.2). */
export function RecoveryKeyCard({ recoveryKey }: Readonly<{ recoveryKey: RecoveryKey }>) {
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
    </section>
  );
}
