import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';

/** Filing signs and approving unlocks a share: both need the personal key first. */
export function RecoveryLocked({ onOpenKeys }: Readonly<{ onOpenKeys: () => void }>) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
      <p className="text-note text-fg-muted">{t('admin.recovery.locked')}</p>
      <Button
        variant="compact"
        className="self-start bg-accent text-accent-on"
        onClick={onOpenKeys}
      >
        {t('admin.recovery.unlock')}
      </Button>
    </div>
  );
}
