import { ChevronDown, RotateCw } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  filterRows,
  initialFilters,
  languageName,
  type TableFilters,
  type TableRow,
} from './filterRows';

export const actionStyle =
  'focus-ring min-h-11 rounded-pill border border-border-card px-4 py-2 text-label font-medium hover:bg-surface-row-hover';

const fieldStyle =
  'focus-ring min-h-11 w-full appearance-none rounded-lg border border-border-field bg-surface-field py-2 ps-3 pe-9 text-note text-fg-strong';
const mobileCell: Partial<Record<string, string>> = {
  language: 'order-1 col-span-1 font-semibold text-fg-strong',
  time: 'order-2 col-span-1 text-end text-fg-muted',
  requested: 'order-2 col-span-1 text-end text-fg-muted',
  requester: 'order-0 col-span-2 font-semibold text-fg-strong',
  status: 'order-3 col-span-2',
  recording: 'order-4',
  verification: 'order-5',
  actions: 'order-last col-span-2',
};

function FilterSelect({
  label,
  className,
  value,
  onChange,
  children,
}: Readonly<{
  label: string;
  className?: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}>) {
  return (
    <label
      className={cn(
        'flex min-w-0 flex-col gap-1.5 text-label font-medium text-fg-muted',
        className
      )}
    >
      {label}
      <span className="relative">
        <select className={fieldStyle} value={value} onChange={(e) => onChange(e.target.value)}>
          {children}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2"
        />
      </span>
    </label>
  );
}
type Props<T> = {
  rows: T[];
  filters: TableFilters;
  onChange: (filters: TableFilters) => void;
  columns: string[];
  cells: (row: T) => ReactNode[];
  onRefresh: () => void;
  onMore?: () => void;
  busy: boolean;
  error: boolean;
  label: string;
};
function TaskFilters({
  rows,
  filters,
  onChange,
}: Readonly<Pick<Props<TableRow>, 'rows' | 'filters' | 'onChange'>>) {
  const { t, i18n } = useTranslation();
  const options = (key: 'language' | 'status') =>
    [
      ...new Set(
        rows
          .map((r) => r[key] ?? '?')
          .concat(filters[key], key === 'language' ? '?' : '')
          .filter(Boolean)
      ),
    ].sort();
  return (
    <div className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:grid-cols-3">
      {(['language', 'status'] as const).map((key) => (
        <FilterSelect
          key={key}
          label={t(`admin.tasks.${key}`)}
          value={filters[key]}
          onChange={(value) => onChange({ ...filters, [key]: value })}
        >
          <option value="">
            {t(key === 'language' ? 'admin.tasks.allLanguages' : 'admin.tasks.allStatuses')}
          </option>
          {options(key).map((value) => (
            <option key={value} value={value}>
              {key === 'status'
                ? t(`admin.tasks.states.${value}`)
                : value === '?'
                  ? t('admin.tasks.unknown')
                  : languageName(value, i18n.language)}
            </option>
          ))}
        </FilterSelect>
      ))}
      <FilterSelect
        label={t('admin.tasks.sort')}
        className="col-span-full sm:col-span-1"
        value={filters.order}
        onChange={(value) =>
          onChange({ ...filters, order: value === 'oldest' ? 'oldest' : 'newest' })
        }
      >
        <option value="newest">{t('admin.tasks.newest')}</option>
        <option value="oldest">{t('admin.tasks.oldest')}</option>
      </FilterSelect>
    </div>
  );
}

function TaskRows<T extends TableRow>({
  rows,
  columns,
  cells,
}: Readonly<Pick<Props<T>, 'rows' | 'columns' | 'cells'>>) {
  const { t } = useTranslation();
  const mobileLabels = columns.includes('requested')
    ? ['requester', 'language', 'requested']
    : ['recording', 'verification'];
  return (
    <table className="block w-full text-start text-note md:table">
      <thead className="sr-only md:not-sr-only">
        <tr className="border-y border-border-divider text-label text-fg-muted">
          {columns.map((c) => (
            <th
              className="px-2 py-2.5 text-start font-medium first:ps-5 last:pe-5"
              key={c}
              scope="col"
            >
              {t(`admin.tasks.${c}`)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="block md:table-row-group">
        {rows.map((row) => (
          <tr
            className="grid grid-cols-2 items-baseline gap-x-3 gap-y-2 border-t border-border-divider px-4 py-4 md:table-row md:first:border-t-0 md:hover:bg-surface-row-hover"
            key={row.id}
          >
            {cells(row).map((cell, index) => {
              const column = columns[index];
              return (
                <td
                  key={column}
                  className={cn(
                    'min-w-0 break-words md:px-2 md:py-3 md:text-start md:first:ps-5 md:last:pe-5',
                    mobileCell[column],
                    column === 'verification' && cell === '—' && 'sr-only md:not-sr-only'
                  )}
                >
                  {mobileLabels.includes(column) && cell !== '—' && (
                    <span className="block text-caption text-fg-muted md:hidden" aria-hidden>
                      {t(`admin.tasks.${column}`)}
                    </span>
                  )}
                  {cell}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TaskTableFooter({
  matches,
  loaded,
  busy,
  onMore,
  onReset,
}: Readonly<{
  matches: number;
  loaded: number;
  busy: boolean;
  onMore?: () => void;
  onReset?: () => void;
}>) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 border-t border-border-divider px-4 py-2 text-label text-fg-muted sm:px-5">
      <div className="py-2">
        <p>{t('admin.tasks.counts', { matches, loaded })}</p>
        {onMore && <p className="text-meta">{t('admin.tasks.scope')}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        {onReset && (
          <button type="button" className={actionStyle} onClick={onReset}>
            {t('admin.tasks.reset')}
          </button>
        )}
        {onMore && (
          <button type="button" className={actionStyle} disabled={busy} onClick={onMore}>
            {t('admin.tasks.more')}
          </button>
        )}
      </div>
    </div>
  );
}

export function TaskTable<T extends TableRow>({
  rows,
  filters,
  onChange,
  columns,
  cells,
  onRefresh,
  onMore,
  busy,
  error,
  label,
}: Readonly<Props<T>>) {
  const { t } = useTranslation();
  const matches = filterRows(rows, filters);
  return (
    <section aria-label={label} className="flex flex-col gap-4">
      <TaskFilters rows={rows} filters={filters} onChange={onChange} />
      <div className="rounded-2xl border border-border-card bg-surface-card">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2 sm:px-5">
          <h2 className="text-body font-semibold text-fg-strong">{label}</h2>
          <button
            type="button"
            className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-pill px-3 text-label font-medium text-fg-muted hover:bg-surface-row-hover disabled:opacity-50"
            disabled={busy}
            onClick={onRefresh}
          >
            <RotateCw aria-hidden className="size-4" />
            {t('admin.tasks.refresh')}
          </button>
        </div>
        {filters.language && filters.language !== '?' && rows.some((r) => r.language === null) && (
          <p className="px-4 pb-3 text-label text-fg-muted sm:px-5">{t('admin.tasks.excluded')}</p>
        )}
        {error && (
          <p role="alert" className="px-4 pb-4 text-note text-fg-status-alert sm:px-5">
            {t('admin.tasks.unavailable')}
          </p>
        )}
        {busy && (
          <p role="status" className="px-4 pb-4 text-note text-fg-muted sm:px-5">
            {t('admin.tasks.loading')}
          </p>
        )}
        {!error && !busy && matches.length === 0 && (
          <p className="border-t border-border-divider px-4 py-6 text-note text-fg-muted sm:px-5">
            {t('admin.tasks.noMatches')}
          </p>
        )}
        {matches.length > 0 && <TaskRows rows={matches} columns={columns} cells={cells} />}
        <TaskTableFooter
          matches={matches.length}
          loaded={rows.length}
          busy={busy}
          onMore={onMore}
          onReset={
            filters.language || filters.status || filters.order !== initialFilters.order
              ? () => onChange(initialFilters)
              : undefined
          }
        />
      </div>
    </section>
  );
}
