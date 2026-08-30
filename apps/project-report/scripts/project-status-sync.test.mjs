import { describe, expect, it } from 'vitest';
import { applyProjectSnapshot, projectItemsFrom } from './project-status-sync.mjs';

const report = () => ({
  meta: { version: '1.5.0', updatedAt: '2026-08-30', source: 'roadmap' },
  milestones: [{
    id: 'M1',
    workPackages: [
      { id: 'WP-001', status: 'planned', health: 'on_track', tracking: { githubIssues: [189] } },
      { id: 'WP-002', status: 'planned', health: 'on_track' },
    ],
  }],
});

describe('applyProjectSnapshot', () => {
  it('derives work-package status and health from matching issue and draft Project items', () => {
    const result = applyProjectSnapshot(report(), [
      { issueNumber: 189, status: 'Implementation', health: 'At risk' },
      { workPackageId: 'WP-002', status: 'Done', health: 'On track' },
    ], '2026-08-31');

    expect(result.milestones[0].workPackages).toMatchObject([
      { id: 'WP-001', status: 'implementation', health: 'at_risk' },
      { id: 'WP-002', status: 'done', health: 'on_track' },
    ]);
    expect(result.meta.updatedAt).toBe('2026-08-31');
  });

  it('does not regress a package to done until every matching item is done', () => {
    const result = applyProjectSnapshot(report(), [
      { issueNumber: 189, status: 'Done', health: 'On track' },
      { issueNumber: 189, status: 'Planned', health: 'Needs attention' },
    ], '2026-08-31');

    expect(result.milestones[0].workPackages[0]).toMatchObject({ status: 'planned', health: 'needs_attention' });
  });

  it('preserves the roadmap-specific Prototype state from a Project item', () => {
    const result = applyProjectSnapshot(report(), [
      { workPackageId: 'WP-002', status: 'Prototype', health: 'On track' },
    ], '2026-08-31');

    expect(result.milestones[0].workPackages[1]).toMatchObject({ status: 'prototype', health: 'on_track' });
  });

  it('updates every work package named in a multi-package Project link', () => {
    const result = applyProjectSnapshot(report(), [
      { workPackageIds: ['WP-001', 'WP-002'], status: 'Testing', health: 'On track' },
    ], '2026-08-31');

    expect(result.milestones[0].workPackages).toMatchObject([
      { id: 'WP-001', status: 'testing' },
      { id: 'WP-002', status: 'testing' },
    ]);
  });
});

describe('projectItemsFrom', () => {
  it('reads comma-separated roadmap links from GitHub Project output', () => {
    expect(projectItemsFrom({ items: [{
      content: { number: 232 },
      'roadmap links': 'WP-015, WP-016, WP-017',
      status: 'Planned',
      health: 'On track',
    }] })).toEqual([{
      issueNumber: 232,
      workPackageId: undefined,
      workPackageIds: ['WP-015', 'WP-016', 'WP-017'],
      status: 'Planned',
      health: 'On track',
    }]);
  });
});
