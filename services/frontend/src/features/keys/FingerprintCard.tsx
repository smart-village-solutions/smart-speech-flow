import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import { Button } from '@/ui/primitives/Button';

/** Read aloud and compared out of band at the ceremony and at recovery approvals (spec A.9). */
export function FingerprintCard({ keys }: Readonly<{ keys: UnlockedKeys }>) {
  const { t } = useTranslation();
  const { keyVault } = useServices();

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.keys.unlockedTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">{t('admin.keys.fingerprintHint')}</p>
      <code className="text-body font-semibold text-fg-strong">{displayFingerprint(keys.fingerprint)}</code>
      <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={() => keyVault.lock()}>
        {t('admin.keys.lockAction')}
      </Button>
    </section>
  );
}
