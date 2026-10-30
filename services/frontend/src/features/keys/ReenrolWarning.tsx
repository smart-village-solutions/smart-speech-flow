import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { Button } from '@/ui/primitives/Button';

interface ReenrolWarningProps {
  onContinue: () => void;
  onCancel: () => void;
}

/** What a new key costs, before anything happens; a custodian sees the shares left (§9.6). */
export function ReenrolWarning({ onContinue, onCancel }: Readonly<ReenrolWarningProps>) {
  const { t } = useTranslation();
  const { recordingKeys } = useServices();
  const impact = useQuery({
    queryKey: ['recording', 'reenrolmentImpact'],
    queryFn: () => recordingKeys.reenrolmentImpact(),
  });
  const custodian = impact.data?.custodian === true;

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">
        {t('admin.keys.reenrol.warningTitle')}
      </h2>
      <ul className="flex list-disc flex-col gap-1.5 ps-5 text-note text-fg-body">
        <li>{t('admin.keys.reenrol.warningLocked')}</li>
        <li>{t('admin.keys.reenrol.warningRecovered')}</li>
        <li>{t('admin.keys.reenrol.warningRequests')}</li>
        {custodian && (
          <li className="font-semibold">
            {t('admin.keys.reenrol.warningCustodian', {
              usable: impact.data?.usableAfter ?? 0,
              k: impact.data?.k ?? 0,
            })}
          </li>
        )}
      </ul>
      {impact.isError && (
        <p role="alert" className="text-label text-fg-status-alert">
          {t('admin.keys.unavailable')}
        </p>
      )}
      <div className="flex items-center gap-4">
        <Button
          variant="compact"
          className="bg-accent text-accent-on"
          // A custodian must see what it costs them: no warning, no new key.
          disabled={!impact.isSuccess}
          onClick={onContinue}
        >
          {t('admin.keys.reenrol.continue')}
        </Button>
        <button type="button" className="text-label font-medium text-fg-muted" onClick={onCancel}>
          {t('admin.keys.reenrol.cancel')}
        </button>
      </div>
    </section>
  );
}
