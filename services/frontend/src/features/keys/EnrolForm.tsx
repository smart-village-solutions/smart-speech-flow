import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import { NewKeyForm } from './NewKeyForm';
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

  if (error === 'stepUp') return <StepUpPrompt />;

  return (
    <NewKeyForm
      title={t('admin.keys.enrolTitle')}
      body={t('admin.keys.enrolBody')}
      action={t('admin.keys.enrolAction')}
      pending={pending}
      error={error === null ? null : t(ERROR_KEYS[error])}
      onSubmit={(passphrase, confirmation) => void submit(passphrase, confirmation)}
    />
  );
}
