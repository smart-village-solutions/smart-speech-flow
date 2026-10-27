import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
import { StepUpPrompt } from './StepUpPrompt';
import { type EnrolmentError, useEnrolment } from './useEnrolment';

const ERROR_KEYS: Record<Exclude<EnrolmentError, 'stepUp'>, string> = {
  mismatch: 'admin.keys.passphraseMismatch',
  weak: 'admin.keys.passphraseWeak',
  failed: 'admin.keys.enrolFailed',
};

export function EnrolForm({ owner }: Readonly<{ owner: KeyOwner }>) {
  const { t } = useTranslation();
  const { submit, error, pending } = useEnrolment(owner);
  const [passphrase, setPassphrase] = useState('');
  const [confirmation, setConfirmation] = useState('');

  if (error === 'stepUp') return <StepUpPrompt />;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(passphrase, confirmation);
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.keys.enrolTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">{t('admin.keys.enrolBody')}</p>
      <TextField
        type="password"
        autoComplete="new-password"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
      />
      <TextField
        type="password"
        autoComplete="new-password"
        label={t('admin.keys.passphraseConfirm')}
        value={confirmation}
        onChange={(event) => setConfirmation(event.target.value)}
        error={error === null ? null : t(ERROR_KEYS[error])}
      />
      <Button type="submit" variant="compact" className="self-start bg-accent text-accent-on" disabled={pending}>
        {t(pending ? 'admin.keys.enrolPending' : 'admin.keys.enrolAction')}
      </Button>
    </form>
  );
}
