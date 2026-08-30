import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const statusByProjectStatus = {
  Idea: 'idea',
  Commissioned: 'commissioned',
  Planned: 'planned',
  Prototype: 'prototype',
  Implementation: 'implementation',
  Optimization: 'optimization',
  Testing: 'testing',
  Acceptance: 'acceptance',
  Done: 'done',
};

const progressByStatus = {
  idea: 0,
  commissioned: 0,
  planned: 10,
  prototype: 20,
  implementation: 45,
  optimization: 70,
  testing: 80,
  acceptance: 90,
  done: 100,
};

const healthByProjectHealth = {
  'On track': 'on_track',
  'Needs attention': 'needs_attention',
  'At risk': 'at_risk',
  Blocked: 'blocked',
};

const healthSeverity = {
  on_track: 0,
  needs_attention: 1,
  at_risk: 2,
  blocked: 3,
};

const statusFor = (items) => {
  if (items.every((item) => item.status === 'Done')) return statusByProjectStatus.Done;
  return items
    .map((item) => statusByProjectStatus[item.status])
    .filter(Boolean)
    .reduce((leastAdvanced, status) => progressByStatus[status] < progressByStatus[leastAdvanced] ? status : leastAdvanced, 'done');
};

const healthFor = (items, fallback) => items
  .map((item) => healthByProjectHealth[item.health])
  .filter(Boolean)
  .reduce((current, health) => healthSeverity[health] > healthSeverity[current] ? health : current, fallback);

const matchesWorkPackage = (workPackage, item) =>
  item.workPackageId === workPackage.id ||
  item.workPackageIds?.includes(workPackage.id) ||
  workPackage.tracking?.githubIssues?.includes(item.issueNumber);

export const applyProjectSnapshot = (report, projectItems, updatedAt) => {
  const result = structuredClone(report);
  result.meta.updatedAt = updatedAt;

  for (const milestone of result.milestones) {
    for (const workPackage of milestone.workPackages) {
      const matches = projectItems.filter((item) => matchesWorkPackage(workPackage, item));
      if (matches.length === 0) continue;
      workPackage.status = statusFor(matches);
      workPackage.health = healthFor(matches, workPackage.health);
    }
  }

  return result;
};

export const projectItemsFrom = (payload) => payload.items.map((item) => ({
  issueNumber: typeof item.content?.number === 'number' ? item.content.number : undefined,
  workPackageId: item['work Package'],
  workPackageIds: String(item['roadmap links'] ?? item['roadmap Links'] ?? item['Roadmap links'] ?? '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
  status: item.status,
  health: item.health,
}));

const argumentValue = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
};

export const syncProjectStatus = ({ owner, projectNumber, reportPath }) => {
  const payload = JSON.parse(execFileSync('gh', [
    'project', 'item-list', projectNumber, '--owner', owner, '--limit', '100', '--format', 'json',
  ], { encoding: 'utf8' }));
  const report = JSON.parse(readFileSync(reportPath, 'utf8'));
  const today = new Date().toISOString().slice(0, 10);
  const result = applyProjectSnapshot(report, projectItemsFrom(payload), today);
  writeFileSync(reportPath, `${JSON.stringify(result, null, 2)}\n`);
  return result;
};

const isMainModule = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) {
  const appRoot = resolve(fileURLToPath(new URL('..', import.meta.url)));
  const result = syncProjectStatus({
    owner: argumentValue('--owner', 'smart-village-solutions'),
    projectNumber: argumentValue('--project', '7'),
    reportPath: argumentValue('--report', resolve(appRoot, 'src/data/project-status.json')),
  });
  console.log(`Synced ${result.milestones.flatMap((milestone) => milestone.workPackages).length} work packages.`);
}
