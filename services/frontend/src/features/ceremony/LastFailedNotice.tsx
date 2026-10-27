import { useTranslation } from 'react-i18next';
import type { FailedCeremony } from '@/domain/recovery/recovery.types';

/** Why the last ceremony ended, for every participant, not only the browser whose check failed. */
export function LastFailedNotice({ failed }: Readonly<{ failed: FailedCeremony }>) {
  const { t } = useTranslation();
  return (
    <p role="alert" className="text-note text-fg-status-alert">
      {failed.reason === 'expired'
        ? t('admin.ceremony.lastExpired')
        : t('admin.ceremony.lastAborted', { reason: failed.reason })}
    </p>
  );
}
