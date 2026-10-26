import { useTranslation } from 'react-i18next';
import type { StepError } from './useCeremony';

/** A failed check has already aborted the ceremony; anything else may be retried. */
export function StepAlert({ error }: Readonly<{ error: Exclude<StepError, 'stepUp'> }>) {
  const { t } = useTranslation();
  const message =
    error === 'failed' ? t('admin.ceremony.stepFailed') : t('admin.ceremony.checkFailed', { reason: error });
  return (
    <p role="alert" className="text-meta text-fg-status-alert print:hidden">
      {message}
    </p>
  );
}
