import { z } from 'zod';
import { type Bytes, utf8 } from '@/core/crypto/bytes';

/** The concept's §8.5 note categories (spec §10.7). */
export const CATEGORIES = [
  'translation_error',
  'omission',
  'asr_error',
  'meaning_altered',
  'misunderstanding',
  'suggestion',
  'limitation',
] as const;
export type Category = (typeof CATEGORIES)[number];

export const MAX_FINDINGS = 10;
export const MAX_FINDING_TEXT = 1000;
export const MAX_OVERALL = 8000;

export interface Finding {
  category: Category;
  text: string;
  suggestion: string;
}

const finding = z.object({
  category: z.enum(CATEGORIES),
  text: z.string().min(1).max(MAX_FINDING_TEXT),
  suggestion: z.string().max(MAX_FINDING_TEXT),
});

const note = z.object({
  v: z.literal(1),
  verification_id: z.string(),
  entry_id: z.string(),
  findings: z.array(finding).max(MAX_FINDINGS),
});

const overall = z.object({
  v: z.literal(1),
  verification_id: z.string(),
  text: z.string().max(MAX_OVERALL),
});

const decoder = new TextDecoder('utf-8', { fatal: true });

/** Throws unless the note names this record and entry: a moved note is not this reviewer's. */
export function parseFindings(plain: Bytes, verificationId: string, entryId: string): Finding[] {
  const parsed = note.parse(JSON.parse(decoder.decode(plain)));
  if (parsed.verification_id !== verificationId || parsed.entry_id !== entryId) {
    throw new Error('note names another record or entry');
  }
  return parsed.findings;
}

export function parseOverall(plain: Bytes, verificationId: string): string {
  const parsed = overall.parse(JSON.parse(decoder.decode(plain)));
  if (parsed.verification_id !== verificationId)
    throw new Error('overall note names another record');
  return parsed.text;
}

/** Only the three fields leave the browser, whatever else an editor keeps beside them. */
export function noteJson(
  verificationId: string,
  entryId: string,
  findings: readonly Finding[]
): Bytes {
  const plain = findings.map(({ category, text, suggestion }) => ({ category, text, suggestion }));
  return utf8(
    JSON.stringify({ v: 1, verification_id: verificationId, entry_id: entryId, findings: plain })
  );
}

export function overallJson(verificationId: string, text: string): Bytes {
  return utf8(JSON.stringify({ v: 1, verification_id: verificationId, text }));
}
