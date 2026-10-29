import { useTranslation } from 'react-i18next';
import type { RequestSummary } from '@/domain/recovery/requests.types';
import { formatDate } from '@/features/archive/format';
import { StatusChip } from './StatusChip';

interface SummaryListProps {
  rows: readonly RequestSummary[];
  empty: string;
  /** The custodian's list names the requester; the supervisor's own list does not. */
  showRequester?: boolean;
  onOpen: (requestId: string) => void;
}

/** Requests as the archive lists conversations: one card, a full-width button per row. */
export function SummaryList({
  rows,
  empty,
  showRequester = false,
  onOpen,
}: Readonly<SummaryListProps>) {
  const { t, i18n } = useTranslation();
  if (rows.length === 0) return <p className="text-note text-fg-muted">{empty}</p>;
  return (
    <ul className="divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card">
      {rows.map((row) => (
        <li key={row.requestId}>
          <button
            type="button"
            onClick={() => onOpen(row.requestId)}
            className="flex w-full items-center gap-3 px-4 py-3 text-start hover:bg-surface-row-hover"
          >
            <span className="flex flex-col">
              <span className="text-note font-semibold text-fg-strong">
                {showRequester ? row.requesterSub : formatDate(row.createdAt, i18n.language)}
              </span>
              <span className="text-label text-fg-muted">
                {t('admin.recovery.requests.conversations', { count: row.conversations })}
              </span>
            </span>
            <span className="min-w-0 flex-1 truncate text-label text-fg-body">{row.reason}</span>
            <StatusChip status={row.status} />
          </button>
        </li>
      ))}
    </ul>
  );
}
