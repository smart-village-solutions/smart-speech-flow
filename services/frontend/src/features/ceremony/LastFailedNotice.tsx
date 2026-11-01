import { useTranslation } from 'react-i18next';
import type { FailedCeremony } from '@/domain/recovery/recovery.types';

interface LastFailedNoticeProps {
  failed: FailedCeremony;
  /** A failed change of custodians leaves the key and its current holders as they were. */
  reshared?: boolean;
}

/** Why the last ceremony ended, for every participant, not only the browser whose check failed. */
export function LastFailedNotice({ failed, reshared = false }: Readonly<LastFailedNoticeProps>) {
  const { t } = useTranslation();
  const expired = reshared ? 'admin.ceremony.reshare.lastExpired' : 'admin.ceremony.lastExpired';
  const aborted = reshared ? 'admin.ceremony.reshare.lastAborted' : 'admin.ceremony.lastAborted';
  return (
    <p role="alert" className="text-note text-fg-status-alert">
      {failed.reason === 'expired' ? t(expired) : t(aborted, { reason: failed.reason })}
    </p>
  );
}
