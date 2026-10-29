import { useTranslation } from 'react-i18next';
import { formatTime } from './format';
import type { Gap } from './timeline';

/** Every gap with its time (spec §10.5): what makes a conversation incomplete. */
export function GapList({ gaps }: Readonly<{ gaps: readonly Gap[] }>) {
  const { t, i18n } = useTranslation();
  return (
    <section className="rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="mb-2 text-note font-semibold text-fg-strong">
        {t('admin.archive.gaps.title')}
      </h2>
      <ul className="flex flex-col gap-1">
        {gaps.map((gap) => (
          <li key={`${gap.kind}-${gap.at}`} className="flex gap-3 text-label text-fg-status-alert">
            <span className="tabular-nums">{formatTime(gap.at, i18n.language)}</span>
            <span>
              {t(`admin.archive.gaps.${gap.kind}`, {
                reason: gap.reason ? t(`admin.archive.closeReason.${gap.reason}`) : '',
              })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
