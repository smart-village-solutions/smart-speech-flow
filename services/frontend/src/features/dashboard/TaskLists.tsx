import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { useInbox } from '@/features/review/useReviews';
import { OVERVIEW, languageName, type TableFilters } from './filterRows';
import { TaskTable, actionStyle } from './TaskTable';

export type TaskTarget = {
  kind: 'recording' | 'review' | 'result' | 'details' | 'session';
  id: string;
};

interface Props {
  filters: TableFilters;
  onChange: (filters: TableFilters) => void;
  open: (target: TaskTarget) => void;
}
export function ConversationTable({ filters, onChange, open }: Readonly<Props>) {
  const { t, i18n } = useTranslation();
  const { dashboard } = useServices();
  const client = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: OVERVIEW,
    queryFn: ({ pageParam, signal }) => dashboard.conversations(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const unique = new Map(query.data?.pages.flatMap((p) => p.items.map((r) => [r.id, r] as const)));
  const rows = [...unique.values()].map((row) => ({
    id: row.id,
    time: row.started_at,
    language: row.customer_language,
    status: row.conversation_status,
    row,
  }));
  return (
    <TaskTable
      rows={rows}
      filters={filters}
      onChange={onChange}
      columns={['time', 'language', 'status', 'recording', 'verification', 'actions']}
      label={t('admin.tasks.conversations')}
      error={query.isError}
      busy={query.isFetching}
      onMore={query.hasNextPage ? () => void query.fetchNextPage() : undefined}
      onRefresh={() => void client.resetQueries({ queryKey: OVERVIEW, exact: true })}
      cells={({ row, language }) => [
        new Date(row.started_at).toLocaleString(i18n.language, {
          dateStyle: 'short',
          timeStyle: 'short',
        }),
        language ? languageName(language, i18n.language) : t('admin.tasks.unknown'),
        t(`admin.tasks.states.${row.conversation_status}`),
        <>
          {t(`admin.tasks.recordings.${row.recording_status}`)}
          {row.recording_access !== 'none' && (
            <div className="text-label text-fg-muted">
              {t(`admin.tasks.access.${row.recording_access}`)}
            </div>
          )}
          {row.origin === 'transferred' && <div>{t('admin.tasks.transferred')}</div>}
        </>,
        row.verification ? t(`admin.tasks.states.${row.verification.status}`) : '—',
        <div className="flex flex-wrap gap-1">
          {row.actions.map((action) => {
            const kind =
              action === 'resume'
                ? 'session'
                : action === 'open_recording'
                  ? 'recording'
                  : 'details';
            const id =
              kind === 'session'
                ? row.session_id
                : kind === 'recording'
                  ? row.recording_id
                  : row.id;
            return (
              id && (
                <button
                  key={action}
                  aria-label={kind === 'session' ? t('admin.sessions.reenter', { id }) : undefined}
                  className={actionStyle}
                  onClick={() => open({ kind, id })}
                >
                  {t(`admin.tasks.${action}`)}
                </button>
              )
            );
          })}
        </div>,
      ]}
    />
  );
}
export function ReviewTable({ filters, onChange, open }: Readonly<Props>) {
  const { t, i18n } = useTranslation();
  const inbox = useInbox();
  const rows = (inbox.data ?? []).map((row) => ({
    id: row.verificationId,
    time: row.requestedAt,
    language: null,
    status: row.status,
    row,
  }));
  return (
    <TaskTable
      rows={rows}
      filters={filters}
      onChange={onChange}
      columns={['requested', 'requester', 'language', 'status', 'actions']}
      label={t('admin.tasks.reviews')}
      error={inbox.isError}
      busy={inbox.isFetching}
      onRefresh={() => void inbox.refetch()}
      cells={({ id, row, status }) => [
        new Date(row.requestedAt).toLocaleString(i18n.language, {
          dateStyle: 'short',
          timeStyle: 'short',
        }),
        row.requestedByName ?? '—',
        t('admin.tasks.unknown'),
        t(`admin.tasks.states.${status}`),
        status === 'approved' || status === 'not_approved' ? (
          <button className={actionStyle} onClick={() => open({ kind: 'result', id })}>
            {t('admin.tasks.openResult')}
          </button>
        ) : (
          row.openable &&
          (status === 'awaiting' || status === 'in_review') && (
            <button className={actionStyle} onClick={() => open({ kind: 'review', id })}>
              {t('admin.tasks.openReview')}
            </button>
          )
        ),
      ]}
    />
  );
}
