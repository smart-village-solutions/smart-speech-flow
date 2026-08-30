import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const parseJson = (value) => JSON.parse(value);

const defaultRun = (command, args) => execFileSync(command, args, { encoding: 'utf8' });

export const collectEvidence = ({
  run = defaultRun,
  readReport = readFileSync,
  owner = 'smart-village-solutions',
  projectNumber = '7',
  reportPath = resolve(fileURLToPath(new URL('../../../apps/project-report/src/data/project-status.json', import.meta.url))),
} = {}) => ({
  collectedAt: new Date().toISOString(),
  openSpec: parseJson(run('openspec', ['change', 'list', '--json'])),
  projectStatus: parseJson(readReport(reportPath, 'utf8')),
  issues: parseJson(run('gh', [
    'issue', 'list', '--state', 'open', '--limit', '100',
    '--json', 'number,title,labels,url,updatedAt',
  ])),
  pullRequests: parseJson(run('gh', [
    'pr', 'list', '--state', 'open', '--limit', '100',
    '--json', 'number,title,headRefName,reviewDecision,statusCheckRollup,url,updatedAt',
  ])),
  projectItems: parseJson(run('gh', [
    'project', 'item-list', projectNumber, '--owner', owner, '--limit', '100', '--format', 'json',
  ])),
});

const isMainModule = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) console.log(JSON.stringify(collectEvidence(), null, 2));
