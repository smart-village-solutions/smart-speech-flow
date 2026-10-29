import { z } from 'zod';
import { type Bytes, utf8 } from '@/core/crypto/bytes';

const time = z.string();
const sha = z
  .string()
  .regex(/^[0-9a-f]{64}$/)
  .nullable();

const step = z.object({ name: z.string() }).passthrough();

/** `record.json` of a stored or failed message (spec §7; `records.message_record`). */
const messageRecord = z.object({
  v: z.literal(1),
  message_id: z.string(),
  sender: z.string(),
  input: z.enum(['audio', 'text']),
  source_lang: z.string(),
  target_lang: z.string(),
  accepted_at: time,
  completed_at: time,
  source_text: z.string().nullable(),
  raw_translation: z.string().nullable(),
  final_text: z.string().nullable(),
  steps: z.array(step),
  hashes: z.object({
    original_audio_sha256: sha,
    asr_input_sha256: sha,
    translated_audio_sha256: sha,
  }),
  error: z
    .object({
      stage: z.string().nullable(),
      code: z.string().nullable(),
      message: z.string().nullable(),
    })
    .optional(),
});

/** `consent.json`: an answer and the evidence it carried (spec §6). */
const consentRecord = z
  .object({
    v: z.literal(1),
    kind: z.string(),
    answer: z.enum(['yes', 'no']),
    answered_at: time,
    requested_by: z.string(),
    window_id: z.string().nullable(),
    legal_basis: z.string(),
    guest: z.object({ name: z.string(), entered_by: z.string() }).optional(),
    signature: z.object({ png: z.string().optional() }).passthrough().optional(),
    id_check: z
      .object({ policy: z.string(), checked: z.boolean(), at: z.string().nullable() })
      .optional(),
    text: z
      .object({
        language: z.string(),
        kind: z.string(),
        source: z.string(),
        version: z.string(),
        sha256: z.string(),
        html: z.string(),
      })
      .optional(),
  })
  .passthrough();

const playbackRecord = z.object({
  v: z.literal(1),
  message_id: z.string(),
  message_entry_id: z.string(),
  event: z.enum(['started', 'completed']),
  reported_by: z.string(),
  at: time,
});

/** `amendment.json` (spec §10.6): written in the browser, never read by the gateway. */
const amendmentRecord = z.object({
  v: z.literal(1),
  references: z.array(z.string().uuid()).min(1).max(20),
  text: z.string().min(1).max(4000),
  author_sub: z.string().min(1),
  written_at: time,
});

export type MessageRecord = z.infer<typeof messageRecord>;
export type ConsentRecord = z.infer<typeof consentRecord>;
export type PlaybackRecord = z.infer<typeof playbackRecord>;
export type AmendmentRecord = z.infer<typeof amendmentRecord>;
export type ParsedRecord =
  | { kind: 'message' | 'failed'; record: MessageRecord }
  | { kind: 'consent'; record: ConsentRecord }
  | { kind: 'playback'; record: PlaybackRecord }
  | { kind: 'amendment'; record: AmendmentRecord };

/** The JSON object of each entry kind (spec §7). */
export const JSON_OBJECT: Readonly<Record<string, string>> = {
  message: 'record.json',
  failed: 'record.json',
  consent: 'consent.json',
  playback: 'playback.json',
  amendment: 'amendment.json',
};

export function parseRecord(kind: string, data: Bytes): ParsedRecord {
  const json: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(data));
  switch (kind) {
    case 'message':
    case 'failed':
      return { kind, record: messageRecord.parse(json) };
    case 'consent':
      return { kind, record: consentRecord.parse(json) };
    case 'playback':
      return { kind, record: playbackRecord.parse(json) };
    case 'amendment':
      return { kind, record: amendmentRecord.parse(json) };
    default:
      throw new TypeError('unknown entry kind');
  }
}

export function newAmendment(
  references: readonly string[],
  text: string,
  authorSub: string,
  now: Date
): Bytes {
  const record = amendmentRecord.parse({
    v: 1,
    references: [...references],
    text,
    author_sub: authorSub,
    written_at: now.toISOString(),
  });
  return utf8(JSON.stringify(record));
}
