import { describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { rankWorkPackages, renderMeetingMinutes } from './priority-report.mjs';

const report = () => ({
  milestones: [
    {
      id: 'M1',
      title: 'Foundation (Deadline: 15.09.2026)',
      workPackages: [
        {
          id: 'WP-001',
          title: 'Secure the service boundary',
          priority: 'must',
          status: 'planned',
          health: 'at_risk',
          dependsOn: [],
        },
        {
          id: 'WP-002',
          title: 'Complete dependent conversation flow',
          priority: 'must',
          status: 'planned',
          health: 'on_track',
          dependsOn: ['WP-001'],
        },
        {
          id: 'WP-003',
          title: 'Already delivered improvement',
          priority: 'must',
          status: 'done',
          health: 'on_track',
          dependsOn: [],
        },
      ],
    },
  ],
});

describe('rankWorkPackages', () => {
  it('puts an at-risk must-have dependency before its blocked dependent', () => {
    const result = rankWorkPackages(report(), { limit: 3, today: '2026-08-30' });

    expect(result.priorities).toMatchObject([
      {
        workPackageId: 'WP-001',
        priority: 'must',
        dependencyState: 'ready',
        source: 'project-status.json',
      },
      {
        workPackageId: 'WP-002',
        dependencyState: 'blocked by WP-001',
      },
    ]);
    expect(result.priorities.map((item) => item.workPackageId)).not.toContain('WP-003');
  });

  it('loads the repository status snapshot when invoked as a CLI', () => {
    const scriptPath = resolve('plugins/project-steward/scripts/priority-report.mjs');
    const output = execFileSync('node', [scriptPath, '--limit', '1', '--today', '2026-08-30'], {
      encoding: 'utf8',
    });

    expect(JSON.parse(output)).toMatchObject({
      generatedAt: '2026-08-30',
      priorities: [{ source: 'project-status.json' }],
    });
  });

  it('renders decisions and actions without retaining raw sensitive notes', () => {
    const minutes = renderMeetingMinutes({
      date: '2026-08-30',
      topic: 'Production recovery',
      decisions: ['Create a recovery test issue.'],
      actions: [{ description: 'Run the recovery exercise.', owner: 'Operations', due: '2026-09-05' }],
      risks: ['Recovery evidence is incomplete.'],
      sources: ['Meeting notes, 2026-08-30'],
      rawNotes: 'Password: do-not-retain',
    });

    expect(minutes).toContain('# Meeting Minutes: Production recovery');
    expect(minutes).toContain('Create a recovery test issue.');
    expect(minutes).toContain('Operations');
    expect(minutes).toContain('2026-09-05');
    expect(minutes).not.toContain('do-not-retain');
  });
});
