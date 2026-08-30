import { describe, expect, it } from 'vitest';
import { collectEvidence } from './evidence-collector.mjs';

describe('collectEvidence', () => {
  it('collects the project plan, OpenSpec, issues, pull requests, and Project items', () => {
    const calls = [];
    const run = (command, args, options) => {
      calls.push([command, args, options]);
      if (command === 'openspec') return JSON.stringify({ changes: [{ id: 'stabilize-production-operations' }] });
      if (args[0] === 'issue') return JSON.stringify([{ number: 221, title: 'Secure service ports' }]);
      if (args[0] === 'pr') return JSON.stringify([{ number: 233, title: 'Boot health gate' }]);
      return JSON.stringify({ items: [{ id: 'PVTI_1' }] });
    };

    const evidence = collectEvidence({
      run,
      readReport: () => JSON.stringify({ meta: { version: '1.6.0' } }),
      owner: 'smart-village-solutions',
      projectNumber: '7',
    });

    expect(evidence).toMatchObject({
      openSpec: { changes: [{ id: 'stabilize-production-operations' }] },
      projectStatus: { meta: { version: '1.6.0' } },
      issues: [{ number: 221 }],
      pullRequests: [{ number: 233 }],
      projectItems: { items: [{ id: 'PVTI_1' }] },
    });
    expect(calls[0].slice(0, 2)).toEqual(['openspec', ['change', 'list', '--json']]);
    expect(calls.map(([command, args]) => [command, args.slice(0, 2)])).toEqual(expect.arrayContaining([
      ['gh', ['issue', 'list']],
      ['gh', ['pr', 'list']],
      ['gh', ['project', 'item-list']],
    ]));
    const issueArgs = calls.find(([, args]) => args[0] === 'issue')[1];
    const pullRequestArgs = calls.find(([, args]) => args[0] === 'pr')[1];
    expect(issueArgs).toEqual(expect.arrayContaining(['--state', 'all']));
    expect(issueArgs.at(-1)).toContain('state');
    expect(pullRequestArgs).toEqual(expect.arrayContaining(['--state', 'all']));
    expect(pullRequestArgs.at(-1)).toContain('mergedAt');
    expect(calls.filter(([command]) => command === 'gh')).toEqual(expect.arrayContaining([
      ['gh', expect.arrayContaining(['--repo', 'smart-village-solutions/smart-speech-flow']), expect.objectContaining({ cwd: expect.any(String) })],
    ]));
  });
});
