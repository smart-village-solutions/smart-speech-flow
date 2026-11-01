import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
import { useUnlock } from './useUnlock';

interface UnlockFormProps {
  owner: KeyOwner;
  ownKey: OwnKey;
}

export function UnlockForm({ owner, ownKey }: Readonly<UnlockFormProps>) {
  const { t } = useTranslation();
  const { submit, failed, pending } = useUnlock(owner, ownKey);
  const [passphrase, setPassphrase] = useState('');

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(passphrase);
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.keys.unlockTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.keys.fingerprintLabel')} <code>{ownKey.fingerprintDisplay}</code>
      </p>
      <TextField
        type="password"
        autoComplete="current-password"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
        error={failed ? t('admin.keys.unlockFailed') : null}
      />
      <Button type="submit" variant="compact" className="self-start bg-accent text-accent-on" disabled={pending}>
        {t(pending ? 'admin.keys.unlockPending' : 'admin.keys.unlockAction')}
      </Button>
    </form>
  );
}
