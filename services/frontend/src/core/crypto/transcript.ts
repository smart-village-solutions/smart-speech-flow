import { type Bytes, fromBuffer, scalarToBytes, toHex } from './bytes';
import { type Field, enc } from './encoding';
import type { Proof } from './proofs';
import { TAGS } from './tags';

const DISPLAY_BYTES = 20;
const PAPER_DEVICE_REF = 'paper-device';

/** fpr = SHA-256(enc(tag, tenant_id, user_sub, enc_pub, sig_pub)) (spec A.9). */
export async function fingerprint(tenantId: string, userSub: string, encPub: Bytes, sigPub: Bytes): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.digest('SHA-256', enc(TAGS.fingerprint, tenantId, userSub, encPub, sigPub)));
}

/** The ceremony device has an encryption key only; it stands in for both halves. */
export function paperDeviceFingerprint(tenantId: string, devicePub: Bytes): Promise<Bytes> {
  return fingerprint(tenantId, PAPER_DEVICE_REF, devicePub, devicePub);
}

/** First 20 bytes, hex, in groups of four: `a1b2 c3d4 …`. */
export function displayFingerprint(raw: Bytes): string {
  return (toHex(raw.slice(0, DISPLAY_BYTES)).match(/.{4}/g) ?? []).join(' ');
}

export interface Participant {
  holderRef: string;
  index: number;
  fingerprint: Bytes;
}

export interface Dealing {
  dealerIndex: number;
  commitments: Bytes[];
  proof: Proof;
}

export interface TranscriptInput {
  tenantId: string;
  ceremonyId: string;
  k: number;
  participants: Participant[];
  dealings: Dealing[];
  recoveryPublicKey: Bytes;
  holderShares: Bytes[];
  gatewayKeys: { keyId: string; publicKey: Bytes }[];
  previousTranscript?: Bytes;
}

const byIndex = <T extends { index: number }>(left: T, right: T) => left.index - right.index;

/** Code-point order, as Python's `sorted` uses; `localeCompare` would differ. */
function compareCodePoints(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

/** Every list in a fixed order: participants and dealings by index, keys by ID (spec A.8). */
function transcriptFields(data: Readonly<TranscriptInput>): Field[] {
  const fields: Field[] = [data.tenantId, data.ceremonyId, data.k, data.participants.length];
  for (const participant of [...data.participants].sort(byIndex)) {
    fields.push(participant.holderRef, participant.index, participant.fingerprint);
  }
  for (const dealing of [...data.dealings].sort((left, right) => left.dealerIndex - right.dealerIndex)) {
    fields.push(dealing.dealerIndex, ...dealing.commitments, scalarToBytes(dealing.proof.c), scalarToBytes(dealing.proof.s));
  }
  fields.push(data.recoveryPublicKey, ...data.holderShares);
  for (const key of [...data.gatewayKeys].sort((left, right) => compareCodePoints(left.keyId, right.keyId))) {
    fields.push(key.keyId, key.publicKey);
  }
  fields.push(data.previousTranscript ?? new Uint8Array(0));
  return fields;
}

export async function transcriptHash(data: Readonly<TranscriptInput>): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.digest('SHA-256', enc(TAGS.transcript, ...transcriptFields(data))));
}
