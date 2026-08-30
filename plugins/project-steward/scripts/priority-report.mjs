import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectEvidence } from './evidence-collector.mjs';

const priorityWeight = {
  must: 0,
  replacement_required: 1,
  valuable: 2,
  requested: 3,
  funded_optional: 4,
  unfunded_nice_to_have: 5,
  irrelevant: 6,
};

const healthWeight = {
  on_track: 0,
  needs_attention: 1,
  at_risk: 2,
  blocked: 3,
};

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

const parseDeadline = (title) => {
  const match = /Deadline:\s*(\d{2})\.(\d{2})\.(\d{4})/.exec(title ?? '');
  return match ? `${match[3]}-${match[2]}-${match[1]}` : undefined;
};

const compareDeadline = (left, right) => (left.deadline ?? '9999-12-31')
  .localeCompare(right.deadline ?? '9999-12-31');

const rationaleFor = (workPackage, dependencyState, dependentCount, deadline) => {
  const rationale = [`Strategic priority: ${workPackage.priority ?? 'unclassified'}.`];
  if (workPackage.health && workPackage.health !== 'on_track') {
    rationale.push(`Health requires attention: ${workPackage.health.replaceAll('_', ' ')}.`);
  }
  if (dependencyState !== 'ready') rationale.push(`Blocked until ${dependencyState.slice('blocked by '.length)} is done.`);
  if (dependentCount > 0) rationale.push(`Unblocks ${dependentCount} direct work package${dependentCount === 1 ? '' : 's'}.`);
  if (deadline) rationale.push(`Milestone deadline: ${deadline}.`);
  return rationale;
};

const projectItemsFor = (workPackage, projectItems) => projectItems.filter((item) => {
  const linkedWorkPackages = String(item['roadmap links'] ?? item['roadmap Links'] ?? item['Roadmap links'] ?? '')
    .split(',')
    .map((value) => value.trim());
  return item['work Package'] === workPackage.id
    || linkedWorkPackages.includes(workPackage.id)
    || workPackage.tracking?.githubIssues?.includes(item.content?.number);
});

export const reconcileEvidence = ({ projectStatus, projectItems = { items: [] }, decisions = [] }) => {
  const report = structuredClone(projectStatus);
  const conflicts = [];

  for (const milestone of report.milestones) {
    for (const workPackage of milestone.workPackages) {
      const items = projectItemsFor(workPackage, projectItems.items ?? []);
      const statuses = [...new Set(items.map((item) => item.status).filter(Boolean))].sort();
      if (statuses.length > 1) {
        conflicts.push({
          workPackageId: workPackage.id,
          source: 'GitHub Project',
          field: 'status',
          values: statuses,
        });
        continue;
      }
      if (statuses.length === 1 && statusByProjectStatus[statuses[0]]) {
        workPackage.status = statusByProjectStatus[statuses[0]];
        workPackage.source = 'GitHub Project';
      }
    }
  }

  for (const decision of decisions) {
    const workPackage = report.milestones.flatMap((milestone) => milestone.workPackages)
      .find((candidate) => candidate.id === decision.workPackageId);
    if (!workPackage) continue;
    if (decision.status) workPackage.status = decision.status;
    if (decision.priority) workPackage.priority = decision.priority;
    workPackage.source = 'documented project decision';
  }

  return { report, conflicts };
};

export const rankWorkPackages = (report, { limit = 5, today = new Date().toISOString().slice(0, 10) } = {}) => {
  const workPackages = report.milestones.flatMap((milestone) => milestone.workPackages.map((workPackage) => ({
    ...workPackage,
    deadline: parseDeadline(milestone.title),
  })));
  const byId = new Map(workPackages.map((workPackage) => [workPackage.id, workPackage]));
  const remaining = workPackages.filter((workPackage) => workPackage.status !== 'done');

  const priorities = remaining.map((workPackage) => {
    const incompleteDependencies = (workPackage.dependsOn ?? [])
      .filter((dependencyId) => byId.get(dependencyId)?.status !== 'done');
    const dependencyState = incompleteDependencies.length === 0
      ? 'ready'
      : `blocked by ${incompleteDependencies.join(', ')}`;
    const dependentCount = remaining.filter((candidate) => candidate.dependsOn?.includes(workPackage.id)).length;

    return {
      workPackageId: workPackage.id,
      title: workPackage.title,
      priority: workPackage.priority ?? 'unclassified',
      status: workPackage.status,
      health: workPackage.health ?? 'on_track',
      deadline: workPackage.deadline,
      dependencyState,
      source: workPackage.source ?? 'project-status.json',
      rationale: rationaleFor(workPackage, dependencyState, dependentCount, workPackage.deadline),
      priorityWeight: priorityWeight[workPackage.priority] ?? Number.MAX_SAFE_INTEGER,
      readinessWeight: dependencyState === 'ready' ? 0 : 1,
      healthWeight: healthWeight[workPackage.health] ?? 0,
      dependentCount,
    };
  }).sort((left, right) => left.priorityWeight - right.priorityWeight
    || left.readinessWeight - right.readinessWeight
    || right.healthWeight - left.healthWeight
    || compareDeadline(left, right)
    || right.dependentCount - left.dependentCount
    || left.workPackageId.localeCompare(right.workPackageId))
    .slice(0, limit)
    .map(({ priorityWeight: _priorityWeight, readinessWeight: _readinessWeight, healthWeight: _healthWeight, dependentCount: _dependentCount, ...priority }) => priority);

  return { generatedAt: today, priorities };
};

export const rankEvidence = (evidence, options = {}) => {
  const { report, conflicts } = reconcileEvidence(evidence);
  const conflictedWorkPackages = new Set(conflicts.map((conflict) => conflict.workPackageId));
  const actionableReport = structuredClone(report);
  for (const milestone of actionableReport.milestones) {
    milestone.workPackages = milestone.workPackages
      .filter((workPackage) => !conflictedWorkPackages.has(workPackage.id));
  }
  return { ...rankWorkPackages(actionableReport, options), conflicts };
};

export const renderPriorityMarkdown = ({ generatedAt, priorities, conflicts = [] }) => [
  `# Next Priorities (${generatedAt})`,
  '',
  ...priorities.flatMap((priority, index) => [
    `## ${index + 1}. ${priority.workPackageId}: ${priority.title}`,
    '',
    `- Strategic priority: ${priority.priority}`,
    `- Status: ${priority.status}; health: ${priority.health}`,
    `- Dependency state: ${priority.dependencyState}`,
    `- Source: ${priority.source}`,
    ...priority.rationale.map((reason) => `- ${reason}`),
    '',
  ]),
  ...(conflicts.length === 0 ? [] : [
    '## Conflicts',
    '',
    ...conflicts.map((conflict) => `- ${conflict.workPackageId}: ${conflict.source} ${conflict.field} conflicts (${conflict.values.join(', ')}). No plan update.`),
    '',
  ]),
].join('\n');

const sanitizeMinuteText = (value) => String(value)
  .replace(/(?:password|token|api(?:[- ]?key)?|secret)\s*[:=]\s*[^;\s]+/gi, '[REDACTED_SECRET]')
  .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[REDACTED_EMAIL]');

const listSection = (heading, entries) => entries.length === 0
  ? []
  : [
    `## ${heading}`,
    '',
    ...entries.map((entry) => `- ${sanitizeMinuteText(entry)}`),
    '',
  ];

export const renderMeetingMinutes = ({
  date,
  topic,
  decisions = [],
  actions = [],
  risks = [],
  sources = [],
}) => [
  `# Meeting Minutes: ${sanitizeMinuteText(topic)}`,
  '',
  `- Date: ${date}`,
  '',
  ...listSection('Decisions', decisions),
  ...listSection('Actions', actions.map((action) => [
    action.description,
    action.owner ? `Owner: ${action.owner}` : undefined,
    action.due ? `Due: ${action.due}` : undefined,
  ].filter(Boolean).join(' — '))),
  ...listSection('Risks', risks),
  ...listSection('Sources', sources),
].join('\n');

const argumentValue = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
};

const isMainModule = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) {
  const repositoryRoot = resolve(fileURLToPath(new URL('../../..', import.meta.url)));
  const reportPath = argumentValue('--report', resolve(repositoryRoot, 'apps/project-report/src/data/project-status.json'));
  const format = argumentValue('--format', 'json');
  const options = {
    limit: Number(argumentValue('--limit', '5')),
    today: argumentValue('--today', new Date().toISOString().slice(0, 10)),
  };
  const result = process.argv.includes('--live')
    ? rankEvidence(collectEvidence({ repositoryRoot, reportPath }), options)
    : rankWorkPackages(JSON.parse(readFileSync(reportPath, 'utf8')), options);
  console.log(format === 'markdown' ? renderPriorityMarkdown(result) : JSON.stringify(result, null, 2));
}
