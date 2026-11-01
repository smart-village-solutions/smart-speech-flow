import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';

/**
 * What the custodians ask the employee for: this browser's own key, never a served
 * value, which a stolen session's re-enrolment would also show (§9.6).
 */
export function OwnFingerprint({ keys }: Readonly<{ keys: UnlockedKeys }>) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border-status bg-surface-card p-4">
      <p className="text-meta font-medium text-fg-muted">{t('admin.keyRecovery.fingerprint')}</p>
      <code className="text-body font-semibold text-fg-strong">
        {displayFingerprint(keys.fingerprint)}
      </code>
      <p className="text-label text-fg-muted">{t('admin.keyRecovery.fingerprintHint')}</p>
    </div>
  );
}
