import { describe, expect, it } from 'vitest';
import { collectEvidence } from './evidence-collector.mjs';

describe('collectEvidence', () => {
  it('collects the project plan, OpenSpec, issues, pull requests, and Project items', () => {
    const calls = [];
    const run = (command, args) => {
      calls.push([command, args]);
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
    expect(calls).toEqual(expect.arrayContaining([
      ['openspec', ['change', 'list', '--json']],
      ['gh', expect.arrayContaining(['issue', 'list'])],
      ['gh', expect.arrayContaining(['pr', 'list'])],
      ['gh', expect.arrayContaining(['project', 'item-list', '7'])],
    ]));
  });
});
