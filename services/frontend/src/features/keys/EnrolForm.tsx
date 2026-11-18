import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import { NewKeyForm } from './NewKeyForm';
import { type EnrolmentError, useEnrolment } from './useEnrolment';

const ERROR_KEYS: Record<EnrolmentError, string> = {
  mismatch: 'admin.keys.passphraseMismatch',
  weak: 'admin.keys.passphraseWeak',
  email: 'admin.keys.emailNotVerified',
  failed: 'admin.keys.enrolFailed',
};

export function EnrolForm({
  owner,
  onPassphraseEntered,
}: Readonly<{ owner: KeyOwner; onPassphraseEntered?: (passphrase: string) => void }>) {
  const { t } = useTranslation();
  const { submit, error, pending } = useEnrolment(owner);

  return (
    <NewKeyForm
      title={t('admin.keys.enrolTitle')}
      body={t('admin.keys.enrolBody')}
      action={t('admin.keys.enrolAction')}
      pending={pending}
      error={error === null ? null : t(ERROR_KEYS[error])}
      onSubmit={submit}
      onPassphraseEntered={onPassphraseEntered}
    />
  );
}
