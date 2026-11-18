import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';
import { downloadPassphrase } from './passphrase-file';

/** The secret is held only while this explicit backup offer is open. */
export function PassphraseBackup({
  passphrase,
  onClose,
}: Readonly<{ passphrase: string; onClose: () => void }>) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  return (
    <ConfirmDialog
      open
      title={t('admin.keys.files.title')}
      body={t('admin.keys.files.warning')}
      confirmLabel={t('admin.keys.files.download')}
      cancelLabel={t('admin.keys.files.skip')}
      error={failed ? t('admin.keys.files.downloadFailed') : null}
      onCancel={onClose}
      onConfirm={() => {
        try {
          downloadPassphrase(passphrase);
          onClose();
        } catch {
          setFailed(true);
        }
      }}
    />
  );
}
