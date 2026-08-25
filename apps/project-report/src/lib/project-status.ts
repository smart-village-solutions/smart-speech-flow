export const projectStatusModel = {
  idea: 0,
  commissioned: 0,
  planned: 10,
  prototype: 20,
  implementation: 45,
  optimization: 70,
  testing: 80,
  acceptance: 90,
  done: 100,
} as const;

export const projectHealthModel = ['on_track', 'needs_attention', 'at_risk', 'blocked'] as const;

export const projectPriorityModel = {
  must: '1: Muss sein',
  replacement_required: '2: Notwendig für die Ablösung des Alt-Systems',
  valuable: '3: Neu, aber sehr sinnvoll',
  requested: '4: Neu und gewünscht',
  funded_optional: '5: Nicht so wichtig, aber finanziert',
  unfunded_nice_to_have: '6: Nice to have, noch ohne Finanzierung',
  irrelevant: '7: Irrelevant',
} as const;

export type ProjectStatus = keyof typeof projectStatusModel;
export type ProjectHealth = (typeof projectHealthModel)[number];
export type ProjectPriority = keyof typeof projectPriorityModel;
export const projectComplexityModel = ['low', 'medium', 'high', 'very_high'] as const;
export type ProjectComplexity = (typeof projectComplexityModel)[number];

export type WorkPackage = {
  id: string;
  title: string;
  area: string;
  complexity: ProjectComplexity;
  priority: ProjectPriority;
  effortPt: number;
  status: ProjectStatus;
  health: ProjectHealth;
  dependsOn: string[];
  acceptanceCriteria?: string[];
  todos?: string[];
  notes?: string;
  featureSummary?: string;
};

export type ProjectStatusReport = {
  meta: { version: string; updatedAt: string; source: string };
  statusModel: typeof projectStatusModel;
  healthModel: readonly ProjectHealth[];
  priorityModel: typeof projectPriorityModel;
  milestones: Array<{
    id: string;
    title: string;
    plannedEffortPt: number;
    sortOrder: number;
    workPackages: WorkPackage[];
  }>;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const hasExactEntries = (value: unknown, expected: Record<string, unknown>) =>
  isRecord(value) &&
  Object.keys(value).length === Object.keys(expected).length &&
  Object.entries(expected).every(([key, entry]) => value[key] === entry);

export const validateProjectStatusReport = (value: unknown): string[] => {
  const errors: string[] = [];
  if (!isRecord(value)) return ['Der Projektstatus muss ein Objekt sein.'];
  const { meta, milestones } = value;
  if (!isRecord(meta) || typeof meta.version !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(String(meta.updatedAt)) || typeof meta.source !== 'string') {
    errors.push('meta benötigt version, updatedAt (YYYY-MM-DD) und source.');
  }
  if (!hasExactEntries(value.statusModel, projectStatusModel)) errors.push('statusModel entspricht nicht dem öffentlichen Fortschrittsmodell.');
  if (!Array.isArray(value.healthModel) || value.healthModel.length !== projectHealthModel.length || value.healthModel.some((entry, index) => entry !== projectHealthModel[index])) errors.push('healthModel entspricht nicht dem öffentlichen Warnstufenmodell.');
  if (!hasExactEntries(value.priorityModel, projectPriorityModel)) errors.push('priorityModel entspricht nicht dem öffentlichen Prioritätsmodell.');
  if (!Array.isArray(milestones)) return [...errors, 'milestones muss ein Array sein.'];

  const milestoneIds = new Set<string>();
  const packageIds = new Set<string>();
  for (const milestone of milestones) {
    if (!isRecord(milestone) || typeof milestone.id !== 'string' || typeof milestone.title !== 'string' || !Number.isFinite(milestone.plannedEffortPt) || !Number.isInteger(milestone.sortOrder) || !Array.isArray(milestone.workPackages)) {
      errors.push('Jeder Meilenstein benötigt gültige Stammdaten und workPackages.');
      continue;
    }
    if (milestoneIds.has(milestone.id)) errors.push(`Doppelte Meilenstein-ID: ${milestone.id}`);
    milestoneIds.add(milestone.id);
    for (const item of milestone.workPackages) {
      if (!isRecord(item) || typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.area !== 'string' || !projectComplexityModel.includes(item.complexity as ProjectComplexity) || !Number.isFinite(item.effortPt) || !Array.isArray(item.dependsOn)) {
        errors.push(`Ungültiges Arbeitspaket in ${milestone.id}.`);
        continue;
      }
      if (packageIds.has(item.id)) errors.push(`Doppelte Arbeitspaket-ID: ${item.id}`);
      packageIds.add(item.id);
      if (!(typeof item.status === 'string' && item.status in projectStatusModel)) errors.push(`Unbekannter Status in ${item.id}.`);
      if (!(typeof item.priority === 'string' && item.priority in projectPriorityModel)) errors.push(`Unbekannte Priorität in ${item.id}.`);
      if (!projectHealthModel.includes(item.health as ProjectHealth)) errors.push(`Unbekannte Warnstufe in ${item.id}.`);
    }
  }
  return errors;
};
