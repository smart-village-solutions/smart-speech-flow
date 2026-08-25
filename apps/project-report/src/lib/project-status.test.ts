import { describe, expect, it } from 'vitest';
import { projectHealthModel, projectPriorityModel, projectStatusModel, validateProjectStatusReport } from './project-status';

const validReport = () => ({
  meta: { version: '1.0.0', updatedAt: '2026-08-09', source: 'test' },
  statusModel: projectStatusModel,
  healthModel: projectHealthModel,
  priorityModel: projectPriorityModel,
  milestones: [{ id: 'M1', title: 'Test', plannedEffortPt: 1, sortOrder: 1, workPackages: [{ id: 'WP-1', title: 'Test', area: 'Test', complexity: 'medium', priority: 'must', effortPt: 1, status: 'planned', health: 'on_track', dependsOn: [] }] }],
});

describe('validateProjectStatusReport', () => {
  it('accepts a valid report', () => expect(validateProjectStatusReport(validReport())).toEqual([]));
  it('rejects duplicate work-package identifiers', () => {
    const report = validReport();
    report.milestones[0].workPackages.push({ ...report.milestones[0].workPackages[0] });
    expect(validateProjectStatusReport(report)).toContain('Doppelte Arbeitspaket-ID: WP-1');
  });
  it('rejects unknown status values', () => {
    const report = validReport();
    report.milestones[0].workPackages[0].status = 'unknown';
    expect(validateProjectStatusReport(report)).toContain('Unbekannter Status in WP-1.');
  });
});
