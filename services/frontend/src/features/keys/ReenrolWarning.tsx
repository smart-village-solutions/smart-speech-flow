import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import { hasPermission } from '@/app/auth/keycloak';

interface ReenrolWarningProps {
  onContinue: () => void;
  onCancel: () => void;
}

/** Explain which work uses the new key before beginning replacement. */
export function ReenrolWarning({ onContinue, onCancel }: Readonly<ReenrolWarningProps>) {
  const { t } = useTranslation();
  const recording = hasPermission('ssf.recording.request');
  const review = hasPermission('ssf.recording.review');
  const notice =
    recording && review ? 'both' : recording ? 'recording' : review ? 'review' : 'personal';

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">
        {t('admin.keys.reenrol.warningTitle')}
      </h2>
      <p>{t(`admin.tasks.replacement.${notice}`)}</p>
      <p>{t('admin.tasks.contact')}</p>
      <div className="flex items-center gap-4">
        <Button variant="compact" className="bg-accent text-accent-on" onClick={onContinue}>
          {t('admin.keys.reenrol.continue')}
        </Button>
        <button type="button" className="text-label font-medium text-fg-muted" onClick={onCancel}>
          {t('admin.keys.reenrol.cancel')}
        </button>
      </div>
    </section>
  );
}
