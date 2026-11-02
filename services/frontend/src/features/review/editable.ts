import type { Finding } from '@/domain/review/findings';

/** A finding while it is edited; the ID only keys the row and never leaves the browser. */
export type EditableFinding = Finding & { id: string };

export function editable(finding: Finding): EditableFinding {
  return { ...finding, id: crypto.randomUUID() };
}
