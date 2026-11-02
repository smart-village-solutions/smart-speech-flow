import { useTranslation } from 'react-i18next';
import type { InboxRow } from '@/domain/review/review.types';
import { formatDate, formatTimeRange } from '@/features/archive/format';
import { useInbox } from './useReviews';

function RowContent({ row }: Readonly<{ row: InboxRow }>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const status = row.openable ? row.status : 'closed';
  return (
    <>
      <span className="flex flex-col">
        <span className="text-note font-semibold text-fg-strong">
          {formatDate(row.startedAt, locale)}
        </span>
        <span className="text-label text-fg-muted">
          {row.endedAt === null ? '' : formatTimeRange(row.startedAt, row.endedAt, locale)} ·{' '}
          {t('admin.review.requestedBy', { name: row.requestedByName ?? row.requestedBy })}
        </span>
      </span>
      <span className="flex-1 text-label text-fg-muted">
        {t('admin.archive.messages', { count: row.messages })}
      </span>
      <span className="rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium text-fg-status">
        {t(`admin.review.status.${status}`)}
      </span>
    </>
  );
}

/** Open assignments first; closed or unreadable rows open nothing (spec §10.7). */
export function ReviewInbox({ onOpen }: Readonly<{ onOpen: (verificationId: string) => void }>) {
  const { t } = useTranslation();
  const inbox = useInbox();
  if (inbox.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.review.unavailable')}
      </p>
    );
  }
  if (inbox.data === undefined) return null;
  if (inbox.data.length === 0)
    return <p className="text-note text-fg-muted">{t('admin.review.empty')}</p>;
  return (
    <ul className="divide-y divide-border-divider rounded-2xl border border-border-card bg-surface-card">
      {inbox.data.map((row) => (
        <li key={row.verificationId}>
          {row.openable ? (
            <button
              type="button"
              onClick={() => onOpen(row.verificationId)}
              className="flex w-full items-center gap-3 px-4 py-3 text-start hover:bg-surface-row-hover"
            >
              <RowContent row={row} />
            </button>
          ) : (
            <div className="flex items-center gap-3 px-4 py-3 opacity-60">
              <RowContent row={row} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
