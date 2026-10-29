import { useTranslation } from 'react-i18next';
import type { OwnConversation } from '@/domain/archive/archive.types';
import { formatDate, formatTimeRange, minutesBetween } from './format';
import { useArchiveList } from './useArchive';

function Chip({ label, alert = false }: Readonly<{ label: string; alert?: boolean }>) {
  const tone = alert ? 'text-fg-status-alert' : 'text-fg-status';
  return (
    <span className={`rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium ${tone}`}>
      {label}
    </span>
  );
}

function Row({ row, onOpen }: Readonly<{ row: OwnConversation; onOpen: (id: string) => void }>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(row.conversationId)}
        className="flex w-full items-center gap-3 px-4 py-3 text-start hover:bg-surface-row-hover"
      >
        <span className="flex flex-col">
          <span className="text-note font-semibold text-fg-strong">
            {formatDate(row.startedAt, locale)}
          </span>
          <span className="text-label text-fg-muted">
            {formatTimeRange(row.startedAt, row.endedAt, locale)}
          </span>
        </span>
        <span className="flex-1 text-label text-fg-muted">
          {t('admin.archive.messages', { count: row.messages })} ·{' '}
          {t('admin.archive.duration', { minutes: minutesBetween(row.startedAt, row.endedAt) })}
        </span>
        <span className="flex flex-wrap justify-end gap-2">
          {row.incomplete && <Chip label={t('admin.archive.incomplete')} alert />}
          {row.legalHold && <Chip label={t('admin.archive.hold')} />}
          <Chip label={t(`admin.archive.verification.${row.verification}`)} />
        </span>
      </button>
    </li>
  );
}

/** Clear metadata only: the guest's name and languages are encrypted (§10.6). */
export function ArchiveList({ onOpen }: Readonly<{ onOpen: (id: string) => void }>) {
  const { t } = useTranslation();
  const list = useArchiveList();
  if (list.isPending) return null;
  if (list.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.archive.unavailable')}
      </p>
    );
  }
  const rows = list.data.pages.flat();
  if (rows.length === 0)
    return <p className="text-note text-fg-muted">{t('admin.archive.empty')}</p>;
  return (
    <>
      <ul className="divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card">
        {rows.map((row) => (
          <Row key={row.conversationId} row={row} onOpen={onOpen} />
        ))}
      </ul>
      {list.hasNextPage && (
        <button
          type="button"
          className="self-start text-label font-medium text-fg-link"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          {t('admin.archive.more')}
        </button>
      )}
    </>
  );
}
