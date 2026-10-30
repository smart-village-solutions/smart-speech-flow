import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import { useOwnCandidates } from './useKeyRecovery';

/** On the archive: conversations the employee's key cannot open, and the way to them (§9.6). */
export function KeyRecoveryBanner({ onOpen }: Readonly<{ onOpen: () => void }>) {
  const { t } = useTranslation();
  const own = useOwnCandidates(true);
  const count = own.data ? own.data.conversations.length + own.data.remaining.conversations : 0;
  if (count === 0) return null;
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5">
      <p className="text-note text-fg-body">{t('admin.keyRecovery.banner', { count })}</p>
      <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={onOpen}>
        {t('admin.keyRecovery.open')}
      </Button>
    </div>
  );
}
