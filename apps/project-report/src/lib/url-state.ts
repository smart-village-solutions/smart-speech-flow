import type { Filters } from './report-model';

export const defaultFilters: Filters = { view: 'milestones', milestone: 'all', status: 'all', priority: 'all', q: '' };
const views = new Set(['milestones', 'work-packages']);

export const parseFilters = (params = new URLSearchParams(window.location.search)): Filters => ({
  view: views.has(params.get('view') ?? '') ? params.get('view') as Filters['view'] : defaultFilters.view,
  milestone: params.get('milestone') || 'all',
  status: params.get('status') || 'all',
  priority: params.get('priority') || 'all',
  q: params.get('q') || '',
});

export const stringifyFilters = (filters: Filters): string => {
  const params = new URLSearchParams();
  if (filters.view !== defaultFilters.view) params.set('view', filters.view);
  if (filters.milestone !== 'all') params.set('milestone', filters.milestone);
  if (filters.status !== 'all') params.set('status', filters.status);
  if (filters.priority !== 'all') params.set('priority', filters.priority);
  if (filters.q.trim()) params.set('q', filters.q.trim());
  return params.toString();
};
