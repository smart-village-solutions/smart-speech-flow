import { type Bytes, fromBuffer, scalarToBytes } from './bytes';
import { decodePoint } from './curve';
import { type Field, enc } from './encoding';

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
