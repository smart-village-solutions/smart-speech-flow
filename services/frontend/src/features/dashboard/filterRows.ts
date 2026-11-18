export interface TableFilters {
  language: string;
  status: string;
  order: 'newest' | 'oldest';
}
export const initialFilters: TableFilters = { language: '', status: '', order: 'newest' };
export interface TableRow {
  id: string;
  time: string;
  language: string | null;
  status: string;
}
export function filterRows<T extends TableRow>(rows: readonly T[], filters: TableFilters): T[] {
  return rows
    .filter(
      (row) =>
        (!filters.language || (row.language ?? '?') === filters.language) &&
        (!filters.status || filters.status === row.status)
    )
    .sort((a, b) => {
      const delta = Date.parse(a.time) - Date.parse(b.time) || a.id.localeCompare(b.id);
      return filters.order === 'oldest' ? delta : -delta;
    });
}

export const OVERVIEW = ['dashboard', 'conversations'] as const;

export function languageName(code: string, locale: string) {
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}
