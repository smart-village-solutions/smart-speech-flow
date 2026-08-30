import { describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import {
  rankEvidence,
  rankWorkPackages,
  renderMeetingMinutes,
  renderPriorityMarkdown,
} from './priority-report.mjs';

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

  it('uses uncontested GitHub Project status over a stale snapshot', () => {
    const result = rankEvidence({
      projectStatus: report(),
      projectItems: { items: [{
        status: 'Done',
        health: 'On track',
        content: { number: 1 },
        'work Package': 'WP-001',
      }] },
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities.map((item) => item.workPackageId)).not.toContain('WP-001');
    expect(result.conflicts).toEqual([]);
  });

  it('uses linked GitHub issue evidence before OpenSpec and the status snapshot', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].status = 'done';
    projectStatus.milestones[0].workPackages[0].tracking = {
      githubIssues: [42],
      openSpecChanges: ['secure-boundary'],
    };

    const result = rankEvidence({
      projectStatus,
      issues: [{ number: 42, state: 'OPEN' }],
      openSpec: [{
        id: 'secure-boundary',
        taskStatus: { total: 2, completed: 2 },
      }],
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities[0]).toMatchObject({
      workPackageId: 'WP-001',
      status: 'planned',
      source: 'GitHub issue #42',
    });
  });

  it('uses a linked open pull request as current implementation evidence', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].tracking = { githubPullRequests: [99] };

    const result = rankEvidence({
      projectStatus,
      pullRequests: [{ number: 99, state: 'OPEN', title: 'Implement the boundary' }],
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities[0]).toMatchObject({
      workPackageId: 'WP-001',
      status: 'implementation',
      source: 'GitHub pull request #99',
    });
  });

  it('does not treat a closed issue as completion evidence', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].tracking = { githubIssues: [42] };

    const result = rankEvidence({
      projectStatus,
      issues: [{ number: 42, state: 'CLOSED' }],
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities[0]).toMatchObject({
      workPackageId: 'WP-001',
      status: 'planned',
      source: 'project-status.json',
    });
  });

  it('uses linked OpenSpec task progress before the status snapshot', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].status = 'planned';
    projectStatus.milestones[0].workPackages[0].tracking = {
      openSpecChanges: ['secure-boundary'],
    };

    const result = rankEvidence({
      projectStatus,
      openSpec: [{
        id: 'secure-boundary',
        taskStatus: { total: 2, completed: 1 },
      }],
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities[0]).toMatchObject({
      workPackageId: 'WP-001',
      status: 'implementation',
      source: 'OpenSpec change secure-boundary',
    });
  });

  it('uses a documented decision before conflicting current GitHub evidence', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].tracking = { githubIssues: [42] };

    const result = rankEvidence({
      projectStatus,
      decisions: [{ workPackageId: 'WP-001', status: 'done' }],
      issues: [{ number: 42, state: 'OPEN' }],
    }, { limit: 3, today: '2026-08-30' });

    expect(result.priorities.map((item) => item.workPackageId)).not.toContain('WP-001');
    expect(result.conflicts).toEqual([]);
  });

  it('reports conflicting GitHub Project status instead of silently ranking it', () => {
    const result = rankEvidence({
      projectStatus: report(),
      projectItems: { items: [
        { status: 'Planned', health: 'On track', 'work Package': 'WP-001' },
        { status: 'Done', health: 'On track', 'work Package': 'WP-001' },
      ] },
    }, { limit: 3, today: '2026-08-30' });

    expect(result.conflicts).toEqual([{
      workPackageId: 'WP-001',
      source: 'GitHub Project',
      field: 'status',
      values: ['Done', 'Planned'],
    }]);
    expect(result.priorities.map((item) => item.workPackageId)).not.toContain('WP-001');
    expect(renderPriorityMarkdown(result)).toContain('## Conflicts');
    expect(renderPriorityMarkdown(result)).toContain('WP-001: GitHub Project status conflicts (Done, Planned). No plan update.');
  });

  it('reports conflicting GitHub source evidence rather than selecting a status', () => {
    const projectStatus = report();
    projectStatus.milestones[0].workPackages[0].tracking = { githubIssues: [42] };
    const result = rankEvidence({
      projectStatus,
      issues: [{ number: 42, state: 'OPEN' }],
      projectItems: { items: [{ status: 'Done', 'work Package': 'WP-001' }] },
    }, { limit: 3, today: '2026-08-30' });

    expect(result.conflicts).toEqual([{
      workPackageId: 'WP-001',
      source: 'GitHub evidence',
      field: 'status',
      values: ['Done', 'Planned'],
    }]);
    expect(result.priorities.map((item) => item.workPackageId)).not.toContain('WP-001');
  });

  it('renders decisions and actions without retaining raw sensitive notes', () => {
    const secretLabel = ['pass', 'word'].join('');
    const minutes = renderMeetingMinutes({
      date: '2026-08-30',
      topic: 'Production recovery',
      decisions: [`Create a recovery test issue. ${secretLabel}: do-not-retain; contact alex@example.com.`],
      actions: [{ description: 'Run the recovery exercise.', owner: 'Operations', due: '2026-09-05' }],
      risks: ['Recovery evidence is incomplete.'],
      sources: ['Meeting notes, 2026-08-30'],
      rawNotes: 'Sensitive transcript detail: do-not-retain',
    });

    expect(minutes).toContain('# Meeting Minutes: Production recovery');
    expect(minutes).toContain('Create a recovery test issue.');
    expect(minutes).toContain('Operations');
    expect(minutes).toContain('2026-09-05');
    expect(minutes).not.toContain('do-not-retain');
    expect(minutes).not.toContain('alex@example.com');
    expect(minutes).toContain('[REDACTED_SECRET]');
    expect(minutes).toContain('[REDACTED_EMAIL]');
  });
});
