import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import { Button } from '@/ui/primitives/Button';
import { StatusChip } from '@/ui/primitives/StatusChip';
import { KeyDetails } from './KeyDetails';

/** Read aloud and compared out of band at the ceremony and at recovery approvals (spec A.9). */
export function FingerprintCard({ keys }: Readonly<{ keys: UnlockedKeys }>) {
  const { t } = useTranslation();
  const { keyVault } = useServices();

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2>
          <StatusChip tone="success">{t('admin.keys.unlockedTitle')}</StatusChip>
        </h2>
        <Button
          variant="compact"
          className="border border-border-card text-label hover:bg-surface-row-hover"
          onClick={() => keyVault.lock()}
        >
          {t('admin.keys.lockAction')}
        </Button>
      </div>
      <KeyDetails fingerprint={displayFingerprint(keys.fingerprint)} />
    </section>
  );
}
