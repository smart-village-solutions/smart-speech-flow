import { useTranslation } from 'react-i18next';
import { clockTime } from '@/lib/sessionTimes';
import { useReenrolmentImpact } from './useKeys';

/**
 * A re-enrolled key waiting for its mailed link (§9.9), read from the gateway so it
 * survives a reload. `requested` is the key just sent, shown until the read catches up.
 */
export function PendingNotice({ requested }: Readonly<{ requested?: string }>) {
  const { t, i18n } = useTranslation();
  const pending = useReenrolmentImpact().data?.pending ?? null;
  if (pending === null && requested === undefined) return null;
  const text =
    pending === null
      ? t('admin.keys.reenrol.pending')
      : t('admin.keys.reenrol.pendingUntil', {
          time: clockTime(new Date(pending.expiresAt).getTime(), i18n.language),
        });
  return (
    <section
      role="status"
      className="flex flex-col gap-2 rounded-2xl border border-border-status bg-surface-card p-5"
    >
      <p className="text-note text-fg-body">{text}</p>
      <code className="text-note font-semibold text-fg-strong">
        {pending?.fingerprintDisplay ?? requested}
      </code>
    </section>
  );
}
