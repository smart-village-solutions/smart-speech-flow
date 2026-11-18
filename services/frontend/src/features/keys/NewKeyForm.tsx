import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';

interface NewKeyFormProps {
  title: string;
  body: string;
  action: string;
  pending: boolean;
  /** The translated error under the confirmation field, if any. */
  error: string | null;
  onSubmit: (passphrase: string, confirmation: string) => Promise<boolean>;
  onPassphraseEntered?: (passphrase: string) => void;
}

/** The passphrase twice: shared by first enrolment and re-enrolment (spec §8.3, §9.6). */
export function NewKeyForm({
  title,
  body,
  action,
  pending,
  error,
  onSubmit,
  onPassphraseEntered,
}: Readonly<NewKeyFormProps>) {
  const { t } = useTranslation();
  const [passphrase, setPassphrase] = useState('');
  const [confirmation, setConfirmation] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void onSubmit(passphrase, confirmation).then((success) => {
      if (success) {
        onPassphraseEntered?.(passphrase);
        setPassphrase('');
        setConfirmation('');
      }
    });
  };

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <div className="space-y-1">
        <h2 className="text-thanks font-semibold text-fg-strong">{title}</h2>
        <p className="max-w-lg text-note leading-chat text-fg-muted">{body}</p>
      </div>
      <TextField
        type="password"
        disabled={pending}
        autoComplete="new-password"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
      />
      <TextField
        type="password"
        disabled={pending}
        autoComplete="new-password"
        label={t('admin.keys.passphraseConfirm')}
        value={confirmation}
        onChange={(event) => setConfirmation(event.target.value)}
        error={error}
      />
      <Button
        type="submit"
        variant="compact"
        className="self-start bg-accent text-accent-on"
        disabled={pending}
      >
        {pending ? t('admin.keys.enrolPending') : action}
      </Button>
    </form>
  );
}
