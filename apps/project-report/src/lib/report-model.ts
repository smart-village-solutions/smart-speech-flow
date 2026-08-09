import type { ProjectComplexity, ProjectHealth, ProjectStatusReport, WorkPackage } from './project-status';

export type Filters = { view: 'milestones' | 'work-packages'; milestone: string; status: string; priority: string; q: string };
export type WorkPackageRow = WorkPackage & { milestoneId: string; milestoneTitle: string; progress: number };
export type MilestoneRow = { id: string; title: string; progress: number; health: ProjectHealth; complexity: ProjectComplexity; workPackageCount: number };

const severity: Record<ProjectHealth, number> = { on_track: 0, needs_attention: 1, at_risk: 2, blocked: 3 };
const complexitySeverity: Record<ProjectComplexity, number> = { low: 0, medium: 1, high: 2, very_high: 3 };
const normalized = (value: string) => value.trim().toLocaleLowerCase('de-DE');

export const flattenWorkPackages = (report: ProjectStatusReport): WorkPackageRow[] => report.milestones.flatMap((milestone) =>
  milestone.workPackages.map((workPackage) => ({ ...workPackage, milestoneId: milestone.id, milestoneTitle: milestone.title, progress: report.statusModel[workPackage.status] }))
);

export const matchesFilters = (item: WorkPackageRow, filters: Filters): boolean => {
  if (filters.milestone !== 'all' && filters.milestone !== item.milestoneId) return false;
  if (filters.status !== 'all' && filters.status !== item.status) return false;
  if (filters.priority !== 'all' && filters.priority !== item.priority) return false;
  const query = normalized(filters.q);
  return !query || [item.id, item.title, item.area, item.milestoneTitle].map(normalized).join(' ').includes(query);
};

export const deriveMilestones = (report: ProjectStatusReport, items: WorkPackageRow[], filters: Filters): MilestoneRow[] => report.milestones
  .map((milestone) => {
    const matching = items.filter((item) => item.milestoneId === milestone.id && item.status !== 'idea');
    const progress = matching.length === 0 ? 0 : Math.round(matching.reduce((total, item) => total + item.progress, 0) / matching.length);
    const health = matching.reduce<ProjectHealth>((current, item) => severity[item.health] > severity[current] ? item.health : current, 'on_track');
    const complexity = matching.reduce<ProjectComplexity>((current, item) => complexitySeverity[item.complexity] > complexitySeverity[current] ? item.complexity : current, 'low');
    return { id: milestone.id, title: milestone.title, progress, health, complexity, workPackageCount: items.filter((item) => item.milestoneId === milestone.id).length };
  })
  .filter((item) => filters.view === 'milestones' ? filters.milestone === 'all' || filters.milestone === item.id : item.workPackageCount > 0)
  .sort((left, right) => report.milestones.find((item) => item.id === left.id)!.sortOrder - report.milestones.find((item) => item.id === right.id)!.sortOrder);
