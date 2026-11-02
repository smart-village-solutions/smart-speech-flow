import type { ArchiveCrypto } from '@/core/crypto/archive-crypto.port';
import { type Bytes, equalBytes } from '@/core/crypto/bytes';
import { signedDigest } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { fingerprint } from '@/core/crypto/transcript';
import { readTimestamp } from '@/core/crypto/tst-info';
import {
  type NoteAddress,
  type VerificationSignatureFields,
  decisionImprint,
  notesDigest,
  verificationFields,
} from '@/core/crypto/verification';
import type {
  DecidedFacts,
  OpenedConversation,
  VerificationRecord,
} from '@/domain/archive/archive.types';
import { type Finding, parseFindings, parseOverall } from '@/domain/review/findings';

/** A finding with a key for rendering only; two identical findings stay two rows. */
export type ShownFinding = Finding & { key: string };

export type RecordState = 'open' | 'closed' | 'verified' | 'broken';

export interface RecordView {
  record: VerificationRecord;
  state: RecordState;
  overall: string | null;
  /** Entry ID to the reviewer's findings on it. */
  findings: Map<string, ShownFinding[]>;
  /** Some notes sit under keys the reader holds no wrap for. */
  missingKeys: boolean;
  /** The authority's time; its CMS signature is not checked (Philipp 27e). */
  stampTime: string | null;
  /** Entries appended after the head this record reviewed. */
  entriesAfter: number;
}

interface Context {
  tenantId: string;
  opened: OpenedConversation;
  keys: ReadonlyMap<string, CryptoKey>;
  archiveCrypto: ArchiveCrypto;
}

class RecordBrokenError extends Error {
  constructor() {
    super('verification record failed its check');
    this.name = 'RecordBrokenError';
  }
}

function check(condition: boolean): void {
  if (!condition) throw new RecordBrokenError();
}

function fieldsOf(
  ctx: Readonly<Context>,
  record: VerificationRecord,
  decided: DecidedFacts,
  digest: Bytes
) {
  return {
    tenantId: ctx.tenantId,
    verificationId: record.verificationId,
    conversationId: ctx.opened.conversation.conversationId,
    reviewedHead: record.reviewedHead ?? new Uint8Array(0),
    outcome: decided.outcome,
    notesDigest: digest,
    snapshot: record.permissionSnapshot ?? [],
  } satisfies VerificationSignatureFields;
}

async function signed(ctx: Readonly<Context>, record: VerificationRecord, decided: DecidedFacts) {
  const key = decided.reviewerKey;
  check(key !== null && record.reviewedHead !== null);
  const owner = await fingerprint(ctx.tenantId, record.reviewerSub, key!.encPub, key!.sigPub);
  check(equalBytes(owner, record.reviewerFingerprint));
  const digest = await notesDigest(decided.overallNote, decided.notes);
  const fields = fieldsOf(ctx, record, decided, digest);
  check(await ctx.archiveCrypto.verifyVerification(key!.sigPub, decided.signature, fields));
  return fields;
}

function address(
  ctx: Readonly<Context>,
  record: VerificationRecord,
  part: NoteAddress['part'],
  entryId: string,
  keyId: string
) {
  return {
    tenantId: ctx.tenantId,
    conversationId: ctx.opened.conversation.conversationId,
    verificationId: record.verificationId,
    part,
    entryId,
    keyId,
  };
}

async function openNotes(
  ctx: Readonly<Context>,
  view: RecordView,
  decided: DecidedFacts
): Promise<void> {
  for (const note of decided.notes) {
    const key = ctx.keys.get(note.keyId);
    if (key === undefined) {
      view.missingKeys = true;
      continue;
    }
    const at = address(ctx, view.record, 'note', note.entryId, note.keyId);
    const plain = await ctx.archiveCrypto.openNote(key, at, note.ciphertext);
    const findings = parseFindings(plain, view.record.verificationId, note.entryId);
    view.findings.set(
      note.entryId,
      findings.map((finding) => ({ ...finding, key: crypto.randomUUID() }))
    );
  }
}

async function openOverall(
  ctx: Readonly<Context>,
  view: RecordView,
  decided: DecidedFacts,
  headIndex: number
): Promise<void> {
  if (decided.overallNote === null) return;
  const head = ctx.opened.entries[headIndex];
  const key = ctx.keys.get(head.keyId);
  if (key === undefined) {
    view.missingKeys = true;
    return;
  }
  const at = address(ctx, view.record, 'overall', head.entryId, head.keyId);
  view.overall = parseOverall(
    await ctx.archiveCrypto.openNote(key, at, decided.overallNote),
    view.record.verificationId
  );
}

async function stampOf(
  fields: VerificationSignatureFields,
  decided: DecidedFacts
): Promise<string | null> {
  if (decided.tsaToken === null) return null;
  const imprint = await decisionImprint(
    await signedDigest(TAGS.verificationSig, verificationFields(fields)),
    decided.signature
  );
  const token = readTimestamp(decided.tsaToken);
  check(equalBytes(token.imprint, imprint));
  return token.genTime;
}

/** Spec §10.7 "Results": each check failing marks only its own record, never as content. */
async function verifyDecided(
  ctx: Readonly<Context>,
  view: RecordView,
  decided: DecidedFacts
): Promise<void> {
  const fields = await signed(ctx, view.record, decided);
  const head = view.record.reviewedHead!;
  const headIndex = ctx.opened.entries.findIndex((entry) => equalBytes(entry.hash, head));
  check(headIndex >= 0);
  view.entriesAfter = ctx.opened.entries.length - 1 - headIndex;
  await openNotes(ctx, view, decided);
  await openOverall(ctx, view, decided, headIndex);
  view.stampTime = await stampOf(fields, decided);
}

function initial(record: VerificationRecord): RecordView {
  const closed = record.status === 'declined' || record.status === 'withdrawn';
  return {
    record,
    state: closed ? 'closed' : 'open',
    overall: null,
    findings: new Map(),
    missingKeys: false,
    stampTime: null,
    entriesAfter: 0,
  };
}

const DECIDED: ReadonlySet<string> = new Set(['approved', 'not_approved']);

/** A decided status stands only with a signed outcome to match it (spec §10.7). */
function unbacked(record: VerificationRecord): boolean {
  return DECIDED.has(record.status) && record.decided?.outcome !== record.status;
}

export async function verifyRecords(ctx: Readonly<Context>): Promise<RecordView[]> {
  const views: RecordView[] = [];
  for (const record of ctx.opened.verifications) {
    const view = initial(record);
    if (unbacked(record)) {
      views.push({ ...view, state: 'broken' });
      continue;
    }
    if (record.decided !== null) {
      try {
        await verifyDecided(ctx, view, record.decided);
        view.state = 'verified';
      } catch {
        views.push({ ...initial(record), state: 'broken' });
        continue;
      }
    }
    views.push(view);
  }
  return views;
}
