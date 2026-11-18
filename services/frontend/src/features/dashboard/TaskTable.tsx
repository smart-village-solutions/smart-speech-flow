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
  'focus-ring rounded-lg border border-border-card px-3 py-2 text-label font-medium hover:bg-surface-row-hover';
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
  const { t, i18n } = useTranslation();
  const matches = filterRows(rows, filters);
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
    <section
      aria-label={label}
      className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-4"
    >
      <h2 className="text-body font-semibold">{label}</h2>
      <div className="flex flex-wrap items-end gap-3">
        {(['language', 'status'] as const).map((key) => (
          <label key={key} className="flex flex-col gap-1 text-label">
            {t(`admin.tasks.${key}`)}
            <select
              className={actionStyle}
              value={filters[key]}
              onChange={(e) => onChange({ ...filters, [key]: e.target.value })}
            >
              <option value="">{t('admin.tasks.all')}</option>
              {options(key).map((value) => (
                <option key={value} value={value}>
                  {key === 'status'
                    ? t(`admin.tasks.states.${value}`)
                    : value === '?'
                      ? t('admin.tasks.unknown')
                      : languageName(value, i18n.language)}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label className="flex flex-col gap-1 text-label">
          {t('admin.tasks.sort')}
          <select
            className={actionStyle}
            value={filters.order}
            onChange={(e) =>
              onChange({ ...filters, order: e.target.value === 'oldest' ? 'oldest' : 'newest' })
            }
          >
            <option value="newest">{t('admin.tasks.newest')}</option>
            <option value="oldest">{t('admin.tasks.oldest')}</option>
          </select>
        </label>
        <button className={actionStyle} onClick={() => onChange(initialFilters)}>
          {t('admin.tasks.reset')}
        </button>
        <button className={actionStyle} disabled={busy} onClick={onRefresh}>
          {t('admin.tasks.refresh')}
        </button>
      </div>
      <p className="text-label text-fg-muted">
        {t('admin.tasks.scope')} ·{' '}
        {t('admin.tasks.counts', { matches: matches.length, loaded: rows.length })}
      </p>
      {filters.language && filters.language !== '?' && rows.some((r) => r.language === null) && (
        <p>{t('admin.tasks.excluded')}</p>
      )}
      {error && <p role="alert">{t('admin.tasks.unavailable')}</p>}
      {busy && <p role="status">{t('admin.tasks.loading')}</p>}
      {!error && !busy && matches.length === 0 && <p>{t('admin.tasks.noMatches')}</p>}
      {matches.length > 0 && (
        <div className="min-w-0">
          <table className="block w-full text-start text-note sm:table">
            <thead className="sr-only sm:not-sr-only">
              <tr>
                {columns.map((c) => (
                  <th className="px-2 py-2 text-start" key={c} scope="col">
                    {t(`admin.tasks.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="block sm:table-row-group">
              {matches.map((row) => (
                <tr
                  className="grid grid-cols-2 gap-2 border-t border-border-divider py-3 sm:table-row"
                  key={row.id}
                >
                  {cells(row).map((cell, index) => (
                    <td key={columns[index]} className="min-w-0 break-words sm:px-2 sm:py-3">
                      <span
                        className="block text-caption font-semibold text-fg-muted sm:hidden"
                        aria-hidden
                      >
                        {t(`admin.tasks.${columns[index]}`)}
                      </span>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {onMore && (
        <button className={actionStyle} disabled={busy} onClick={onMore}>
          {t('admin.tasks.more')}
        </button>
      )}
    </section>
  );
}
