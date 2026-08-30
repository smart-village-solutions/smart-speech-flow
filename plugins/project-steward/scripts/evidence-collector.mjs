import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const parseJson = (value) => JSON.parse(value);

const defaultRun = (command, args, options = {}) => execFileSync(command, args, { encoding: 'utf8', ...options });

export const collectEvidence = ({
  run = defaultRun,
  readReport = readFileSync,
  owner = 'smart-village-solutions',
  projectNumber = '7',
  repositoryRoot = resolve(fileURLToPath(new URL('../../..', import.meta.url))),
  reportPath = resolve(repositoryRoot, 'apps/project-report/src/data/project-status.json'),
} = {}) => {
  const repository = `${owner}/smart-speech-flow`;
  const runOptions = { cwd: repositoryRoot };
  return {
    collectedAt: new Date().toISOString(),
    openSpec: parseJson(run('openspec', ['change', 'list', '--json'], runOptions)),
    projectStatus: parseJson(readReport(reportPath, 'utf8')),
    issues: parseJson(run('gh', [
      'issue', 'list', '--repo', repository, '--state', 'open', '--limit', '100',
      '--json', 'number,title,labels,url,updatedAt',
    ], runOptions)),
    pullRequests: parseJson(run('gh', [
      'pr', 'list', '--repo', repository, '--state', 'open', '--limit', '100',
      '--json', 'number,title,headRefName,reviewDecision,statusCheckRollup,url,updatedAt',
    ], runOptions)),
    projectItems: parseJson(run('gh', [
      'project', 'item-list', projectNumber, '--owner', owner, '--limit', '100', '--format', 'json',
    ], runOptions)),
  };
};

const isMainModule = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) console.log(JSON.stringify(collectEvidence(), null, 2));
