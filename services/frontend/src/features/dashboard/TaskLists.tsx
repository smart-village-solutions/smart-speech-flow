import { useEffect, useState } from 'react';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { describeStart } from '@/lib/sessionTimes';
import { useStaffContent } from '@/features/content/useStaffContent';
import { useServices } from '@/app/providers/services';
import { Button } from '@/ui/primitives/Button';
import { StatusChip } from '@/ui/primitives/StatusChip';
import type { StatusTone } from '@/ui/primitives/statusTones';
import { useInbox } from '@/features/review/useReviews';
import { OVERVIEW, languageName, type TableFilters } from './filterRows';
import { TaskTable, actionStyle } from './TaskTable';

const tones: Partial<Record<string, StatusTone>> = {
  active: 'success',
  approved: 'success',
  pending: 'warning',
  awaiting: 'warning',
  in_review: 'warning',
  not_approved: 'danger',
};

function TaskStatus({ status }: Readonly<{ status: string }>) {
  const { t } = useTranslation();
  return (
    <StatusChip
      tone={tones[status]}
      className="h-auto px-2.5 py-0.5 text-label"
      showIndicator={false}
    >
      {t(`admin.tasks.states.${status}`)}
    </StatusChip>
  );
}

const primaryAction =
  'min-h-11 md:w-full bg-accent px-4 text-label text-accent-on hover:opacity-90';

function useTaskTimestamp() {
  const { t, i18n } = useTranslation();
  const { content } = useStaffContent();
  const timeZone = content?.timeZone ?? undefined;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const fullDate = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone,
  });

  return (iso: string) => {
    const date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return '—';
    const absolute = fullDate.format(date);
    const start = describeStart(iso, now, i18n.language, timeZone ?? null);
    return (
      <time dateTime={iso} title={absolute} className="whitespace-nowrap tabular-nums">
        {start.day === 'other' ? absolute : t(`admin.sessions.${start.day}`, { time: start.time })}
      </time>
    );
  };
}

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
  const timestamp = useTaskTimestamp();
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
      columns={['language', 'time', 'status', 'recording', 'verification', 'actions']}
      label={t('admin.tasks.conversations')}
      error={query.isError}
      busy={query.isFetching}
      onMore={query.hasNextPage ? () => void query.fetchNextPage() : undefined}
      onRefresh={() => void client.resetQueries({ queryKey: OVERVIEW, exact: true })}
      cells={({ row, language }) => [
        language ? languageName(language, i18n.language) : t('admin.tasks.unknown'),
        timestamp(row.started_at),
        <TaskStatus status={row.conversation_status} />,
        <>
          {t(`admin.tasks.recordings.${row.recording_status}`)}
          {row.recording_access !== 'none' && (
            <div className="text-label text-fg-muted">
              {t(`admin.tasks.access.${row.recording_access}`)}
            </div>
          )}
          {row.origin === 'transferred' && <div>{t('admin.tasks.transferred')}</div>}
        </>,
        row.verification ? <TaskStatus status={row.verification.status} /> : '—',
        <div className="flex flex-wrap gap-1.5">
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
            const primary = action !== 'open_details' || row.actions.length === 1;
            return (
              id && (
                <Button
                  variant="compact"
                  key={action}
                  aria-label={kind === 'session' ? t('admin.sessions.reenter', { id }) : undefined}
                  className={primary ? primaryAction : actionStyle}
                  onClick={() => open({ kind, id })}
                >
                  {t(`admin.tasks.${action}`)}
                </Button>
              )
            );
          })}
        </div>,
      ]}
    />
  );
}
export function ReviewTable({ filters, onChange, open }: Readonly<Props>) {
  const { t } = useTranslation();
  const timestamp = useTaskTimestamp();
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
      columns={['requester', 'language', 'requested', 'status', 'actions']}
      label={t('admin.tasks.reviews')}
      error={inbox.isError}
      busy={inbox.isFetching}
      onRefresh={() => void inbox.refetch()}
      cells={({ id, row, status }) => [
        row.requestedByName ?? '—',
        t('admin.tasks.unknown'),
        timestamp(row.requestedAt),
        <TaskStatus status={status} />,
        status === 'approved' || status === 'not_approved' ? (
          <Button
            variant="compact"
            className={primaryAction}
            onClick={() => open({ kind: 'result', id })}
          >
            {t('admin.tasks.openResult')}
          </Button>
        ) : (
          row.openable &&
          (status === 'awaiting' || status === 'in_review') && (
            <Button
              variant="compact"
              className={primaryAction}
              onClick={() => open({ kind: 'review', id })}
            >
              {t('admin.tasks.openReview')}
            </Button>
          )
        ),
      ]}
    />
  );
}
