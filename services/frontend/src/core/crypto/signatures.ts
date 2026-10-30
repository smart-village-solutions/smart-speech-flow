import { type Bytes, fromBuffer, scalarToBytes } from './bytes';
import { decodePoint } from './curve';
import { type Field, codePointOrder, enc } from './encoding';

const ECDSA = { name: 'ECDSA', hash: 'SHA-256' } as const;
const SIGNATURE_BYTES = 64;

/** SHA-256(enc(tag, fields…)); ECDSA-SHA256 hashes this digest once more (spec A.6). */
export async function signedDigest(tag: string, fields: readonly Field[]): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.digest('SHA-256', enc(tag, ...fields)));
}

/** IEEE P1363 `r ‖ s`, which is what WebCrypto produces and the gateway expects. */
export async function signFields(privateKey: CryptoKey, tag: string, fields: readonly Field[]): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.sign(ECDSA, privateKey, await signedDigest(tag, fields)));
}

export async function verifyFields(
  publicKey: Bytes,
  signature: Bytes,
  tag: string,
  fields: readonly Field[]
): Promise<boolean> {
  if (signature.length !== SIGNATURE_BYTES) return false;
  try {
    decodePoint(publicKey);
    const key = await crypto.subtle.importKey('raw', publicKey, { name: 'ECDSA', namedCurve: 'P-256' }, false, [
      'verify',
    ]);
    return await crypto.subtle.verify(ECDSA, key, signature, await signedDigest(tag, fields));
  } catch {
    return false;
  }
}

export interface WrapSignatureFields {
  tenantId: string;
  conversationId: string;
  keyId: string;
  ephemeral: Bytes;
  recipientKind: string;
  recipientRef: string;
  recipientFingerprint: Bytes;
}

/** The fields a wrap signature covers; the gateway signs the same tuple. */
export function wrapFields(wrap: Readonly<WrapSignatureFields>): Field[] {
  return [
    wrap.tenantId,
    wrap.conversationId,
    wrap.keyId,
    wrap.ephemeral,
    wrap.recipientKind,
    wrap.recipientRef,
    wrap.recipientFingerprint,
  ];
}

export interface DealingSignatureFields {
  tenantId: string;
  ceremonyId: string;
  dealerIndex: number;
  commitments: readonly Bytes[];
  proof: { c: bigint; s: bigint };
}

/** What a dealer signs, so a server cannot swap in a dealing of its own; the gateway checks the same tuple. */
export function dealingFields(dealing: Readonly<DealingSignatureFields>): Field[] {
  return [
    dealing.tenantId,
    dealing.ceremonyId,
    dealing.dealerIndex,
    dealing.commitments.length,
    ...dealing.commitments,
    scalarToBytes(dealing.proof.c),
    scalarToBytes(dealing.proof.s),
  ];
}

export async function sha256(data: Bytes): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.digest('SHA-256', data));
}

export interface DigestedHolder {
  index: number;
  holderRef: string;
  fingerprint: Bytes;
}

/** The new holder set a resharing dealer consents to, in index order (spec §9.7). */
export function participantsDigest(holders: readonly DigestedHolder[]): Promise<Bytes> {
  const ordered = [...holders].sort((left, right) => left.index - right.index);
  return sha256(enc(...ordered.flatMap((holder) => [holder.index, holder.holderRef, holder.fingerprint])));
}

export interface ReshareDealingSignatureFields extends DealingSignatureFields {
  previousTranscript: Bytes;
  participantsDigest: Bytes;
}

/** A first-ceremony dealing's fields, bound to the generation it leaves and the one it makes. */
export function reshareDealingFields(dealing: Readonly<ReshareDealingSignatureFields>): Field[] {
  return [...dealingFields(dealing), dealing.previousTranscript, dealing.participantsDigest];
}

export interface ScopePair {
  conversationId: string;
  keyId: string;
}

/** An access request is a supervisor's; a key recovery is an employee's own (spec §9.6). */
export type RequestKind = 'access' | 'key_recovery';

export interface RequestSignatureFields {
  tenantId: string;
  requestId: string;
  kind: RequestKind;
  recoveryKeyId: string;
  requesterSub: string;
  reasonHash: Bytes;
  scope: readonly ScopePair[];
}

/** What a requester signs, so nobody can widen the scope custodians approve (spec §9.5). */
export function requestFields(request: Readonly<RequestSignatureFields>): Field[] {
  const pairs = [...request.scope].sort(
    (a, b) => codePointOrder(a.conversationId, b.conversationId) || codePointOrder(a.keyId, b.keyId)
  );
  return [
    request.tenantId,
    request.requestId,
    request.kind,
    request.recoveryKeyId,
    request.requesterSub,
    request.reasonHash,
    pairs.length,
    ...pairs.flatMap((pair) => [pair.conversationId, pair.keyId]),
  ];
}

export interface ApprovalSignatureFields {
  tenantId: string;
  requestId: string;
  holderIndex: number;
  attempt: number;
  /** Per key, SHA-256 of the partial blob's JSON text exactly as posted. */
  partials: readonly { keyId: string; hash: Bytes }[];
}

/** What a custodian signs: a bad partial under a good signature is theirs (spec §9.5). */
export function approvalFields(approval: Readonly<ApprovalSignatureFields>): Field[] {
  const partials = [...approval.partials].sort((a, b) => codePointOrder(a.keyId, b.keyId));
  return [
    approval.tenantId,
    approval.requestId,
    approval.holderIndex,
    approval.attempt,
    partials.length,
    ...partials.flatMap((partial) => [partial.keyId, partial.hash]),
  ];
}
