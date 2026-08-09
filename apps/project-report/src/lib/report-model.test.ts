import { describe, expect, it } from 'vitest';
import { deriveMilestones, flattenWorkPackages } from './report-model';
import type { ProjectStatusReport } from './project-status';

const report = {
  meta: { version: '1', updatedAt: '2026-08-09', source: 'test' },
  statusModel: { idea: 0, commissioned: 0, planned: 10, prototype: 20, implementation: 45, optimization: 70, testing: 80, acceptance: 90, done: 100 },
  healthModel: ['on_track', 'needs_attention', 'at_risk', 'blocked'],
  priorityModel: { must: '1: Muss sein', replacement_required: '2: Notwendig für die Ablösung des Alt-Systems', valuable: '3: Neu, aber sehr sinnvoll', requested: '4: Neu und gewünscht', funded_optional: '5: Nicht so wichtig, aber finanziert', unfunded_nice_to_have: '6: Nice to have, noch ohne Finanzierung', irrelevant: '7: Irrelevant' },
  milestones: [{ id: 'M1', title: 'Test', plannedEffortPt: 3, sortOrder: 1, workPackages: [
    { id: 'WP-1', title: 'Done', area: 'Test', complexity: 'high', priority: 'must', effortPt: 2, status: 'done', health: 'needs_attention', dependsOn: [] },
    { id: 'WP-2', title: 'Idea', area: 'Test', complexity: 'very_high', priority: 'valuable', effortPt: 1, status: 'idea', health: 'blocked', dependsOn: [] }
  ] }]
} as ProjectStatusReport;

describe('deriveMilestones', () => it('excludes ideas from effort, progress, and health', () => {
  const rows = flattenWorkPackages(report);
  const result = deriveMilestones(report, rows, { view: 'milestones', milestone: 'all', status: 'all', priority: 'all', q: '' })[0];
  expect(result).toMatchObject({ progress: 100, health: 'needs_attention', complexity: 'high', workPackageCount: 2 });
}));
