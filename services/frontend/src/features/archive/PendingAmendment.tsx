import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import type { Amend } from './useAmend';

/** An amendment the gateway may hold in its chain, whose bytes only this page still has. */
export function PendingAmendment({ amend }: Readonly<{ amend: Amend }>) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5"
    >
      <p className="text-note text-fg-status-alert">{t('admin.archive.amendment.pending')}</p>
      <Button
        variant="compact"
        className="self-start bg-accent text-accent-on"
        disabled={amend.pending}
        onClick={() => void amend.retry()}
      >
        {t('admin.archive.amendment.retry')}
      </Button>
    </div>
  );
}
