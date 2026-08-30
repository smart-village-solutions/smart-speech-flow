import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
      source: 'project-status.json',
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

export const renderPriorityMarkdown = ({ generatedAt, priorities }) => [
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
].join('\n');

const listSection = (heading, entries) => entries.length === 0
  ? []
  : [
    `## ${heading}`,
    '',
    ...entries.map((entry) => `- ${entry}`),
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
  `# Meeting Minutes: ${topic}`,
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
  const result = rankWorkPackages(JSON.parse(readFileSync(reportPath, 'utf8')), {
    limit: Number(argumentValue('--limit', '5')),
    today: argumentValue('--today', new Date().toISOString().slice(0, 10)),
  });
  console.log(format === 'markdown' ? renderPriorityMarkdown(result) : JSON.stringify(result, null, 2));
}
