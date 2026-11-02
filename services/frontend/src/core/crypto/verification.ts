import { type Bytes, concat } from './bytes';
import { type Field, codePointOrder, enc } from './encoding';
import { sha256 } from './signatures';
import { TAGS } from './tags';

/** Where a note sits; every field is bound into its AEAD (spec A.3a). */
export interface NoteAddress {
  tenantId: string;
  conversationId: string;
  verificationId: string;
  part: 'note' | 'overall';
  entryId: string;
  keyId: string;
}

type NoteScope = Pick<NoteAddress, 'tenantId' | 'conversationId' | 'verificationId'>;

/** The one place a note's address is built; the writer and every reader must agree on it. */
export function noteAddress(
  scope: Readonly<NoteScope>,
  part: NoteAddress['part'],
  entryId: string,
  keyId: string
): NoteAddress {
  const { tenantId, conversationId, verificationId } = scope;
  return { tenantId, conversationId, verificationId, part, entryId, keyId };
}

export interface SealedNote {
  entryId: string;
  keyId: string;
  ciphertext: Bytes;
}

export interface VerificationSignatureFields {
  tenantId: string;
  verificationId: string;
  conversationId: string;
  reviewedHead: Bytes;
  outcome: string;
  notesDigest: Bytes;
  snapshot: readonly string[];
}

const OUTCOMES: readonly string[] = ['approved', 'not_approved'];

export function noteAad(address: Readonly<NoteAddress>): Bytes {
  return enc(
    TAGS.verificationNote,
    address.tenantId,
    address.conversationId,
    address.verificationId,
    address.part,
    address.entryId,
    address.keyId
  );
}

/** Each ciphertext is hashed, so the digest never meets the 65,535-byte field limit. */
export async function notesDigest(
  overall: Bytes | null,
  notes: readonly Readonly<SealedNote>[]
): Promise<Bytes> {
  const ordered = [...notes].sort((left, right) => codePointOrder(left.entryId, right.entryId));
  const fields: Field[] = [
    overall === null ? new Uint8Array(0) : await sha256(overall),
    ordered.length,
  ];
  for (const note of ordered) fields.push(note.entryId, note.keyId, await sha256(note.ciphertext));
  return sha256(enc(...fields));
}

export function verificationFields(record: Readonly<VerificationSignatureFields>): Field[] {
  if (!OUTCOMES.includes(record.outcome)) throw new Error('an outcome is approved or not_approved');
  const members = [...record.snapshot].sort(codePointOrder);
  return [
    record.tenantId,
    record.verificationId,
    record.conversationId,
    record.reviewedHead,
    record.outcome,
    record.notesDigest,
    members.length,
    ...members,
  ];
}

export function decisionImprint(signedDigest: Bytes, signature: Bytes): Promise<Bytes> {
  return sha256(concat(signedDigest, signature));
}
