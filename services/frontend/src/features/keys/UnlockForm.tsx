import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
import { KeyDetails } from './KeyDetails';
import { PassphraseImport } from './PassphraseImport';
import { useUnlock } from './useUnlock';

interface UnlockFormProps {
  owner: KeyOwner;
  ownKey: OwnKey;
  fileEnabled?: boolean;
  onPassphraseEntered?: (passphrase: string) => void;
}

export function UnlockForm({
  owner,
  ownKey,
  fileEnabled = false,
  onPassphraseEntered,
}: Readonly<UnlockFormProps>) {
  const { t } = useTranslation();
  const { submit, failed, pending } = useUnlock(owner, ownKey);
  const [passphrase, setPassphrase] = useState('');

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(passphrase).then((success) => {
      if (success) {
        onPassphraseEntered?.(passphrase);
        setPassphrase('');
      }
    });
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <h2 className="text-thanks font-semibold text-fg-strong">{t('admin.keys.unlockTitle')}</h2>
      <TextField
        type="password"
        disabled={pending}
        autoComplete="current-password"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
        error={failed ? t('admin.keys.unlockFailed') : null}
      />
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <Button
          type="submit"
          variant="compact"
          className="min-h-11 bg-accent text-accent-on"
          disabled={pending}
        >
          {t(pending ? 'admin.keys.unlockPending' : 'admin.keys.unlockAction')}
        </Button>
        {fileEnabled && <PassphraseImport onLoad={setPassphrase} disabled={pending} />}
      </div>
      <KeyDetails fingerprint={ownKey.fingerprintDisplay} />
    </form>
  );
}
