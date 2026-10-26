import { aesDecrypt, aesEncrypt } from './aead';
import { type Bytes, concat, fromBase64Url, fromBuffer, randomBytes, toBase64Url, utf8 } from './bytes';
import { decodePoint, encodePoint, multiply, publicPoint, randomScalar } from './curve';
import { type Field, enc } from './encoding';
import { type SealedType, isSealedType } from './tags';

const NONCE_BYTES = 12;

/** A payload of the wrong type, shape or context, or a failed tag. */
class SealedPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SealedPayloadError';
  }
}

export interface Sealed {
  type: SealedType;
  ephemeral: Bytes;
  nonce: Bytes;
  ciphertext: Bytes;
}

/** Same key order and no whitespace as the gateway's `Sealed.to_json`. */
export function sealedToJson(sealed: Readonly<Sealed>): string {
  return JSON.stringify({
    v: 1,
    t: sealed.type,
    R: toBase64Url(sealed.ephemeral),
    nonce: toBase64Url(sealed.nonce),
    ct: toBase64Url(sealed.ciphertext),
  });
}

function readString(body: Record<string, unknown>, name: string): string {
  const value = body[name];
  if (typeof value !== 'string') throw new SealedPayloadError('malformed sealed payload');
  return value;
}

export function parseSealed(text: string, expected: SealedType): Sealed {
  const body: unknown = JSON.parse(text);
  if (typeof body !== 'object' || body === null) throw new SealedPayloadError('malformed sealed payload');
  const record = body as Record<string, unknown>;
  const type = readString(record, 't');
  if (record.v !== 1 || type !== expected || !isSealedType(type)) {
    throw new SealedPayloadError('unexpected sealed payload type');
  }
  const ephemeral = fromBase64Url(readString(record, 'R'));
  decodePoint(ephemeral);
  return {
    type,
    ephemeral,
    nonce: fromBase64Url(readString(record, 'nonce')),
    ciphertext: fromBase64Url(readString(record, 'ct')),
  };
}

/** K = HKDF-SHA256(ikm = Z, salt = R ‖ P, info = T) (spec A.4). */
async function payloadKey(sharedX: Bytes, ephemeral: Bytes, recipient: Bytes, type: SealedType): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey('raw', sharedX, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'HKDF', hash: 'SHA-256', salt: concat(ephemeral, recipient), info: utf8(type) },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );
}

export interface SealOptions {
  /** Vector tests only: a fixed ephemeral scalar and nonce. */
  ephemeralScalar?: bigint;
  nonce?: Bytes;
}

export async function seal(
  type: SealedType,
  recipient: Bytes,
  plaintext: Bytes,
  context: readonly Field[],
  options: Readonly<SealOptions> = {}
): Promise<Sealed> {
  const scalar = options.ephemeralScalar ?? randomScalar();
  const ephemeral = publicPoint(scalar);
  const sharedX = encodePoint(multiply(decodePoint(recipient), scalar)).slice(1, 33);
  const key = await payloadKey(sharedX, ephemeral, recipient, type);
  const nonce = options.nonce ?? randomBytes(NONCE_BYTES);
  const ciphertext = await aesEncrypt(key, nonce, plaintext, enc(type, ...context));
  return { type, ephemeral, nonce, ciphertext };
}

/** Open given Z directly; recovery computes Z by combining partials. */
export async function openWithSharedX(
  sealed: Readonly<Sealed>,
  sharedX: Bytes,
  recipient: Bytes,
  context: readonly Field[]
): Promise<Bytes> {
  const key = await payloadKey(sharedX, sealed.ephemeral, recipient, sealed.type);
  try {
    return await aesDecrypt(key, sealed.nonce, sealed.ciphertext, enc(sealed.type, ...context));
  } catch {
    throw new SealedPayloadError('sealed payload failed authentication');
  }
}

/** Z = x-coordinate of d·R, computed inside WebCrypto so `d` never leaves its CryptoKey. */
async function deriveSharedX(privateKey: CryptoKey, ephemeral: Bytes): Promise<Bytes> {
  decodePoint(ephemeral);
  const peer = await crypto.subtle.importKey('raw', ephemeral, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  return fromBuffer(await crypto.subtle.deriveBits({ name: 'ECDH', public: peer }, privateKey, 256));
}

export async function openWithPrivateKey(
  sealed: Readonly<Sealed>,
  privateKey: CryptoKey,
  recipient: Bytes,
  context: readonly Field[]
): Promise<Bytes> {
  return openWithSharedX(sealed, await deriveSharedX(privateKey, sealed.ephemeral), recipient, context);
}

export const contexts = {
  ckWrap: (tenantId: string, conversationId: string, keyId: string, recipientKind: string, recipientRef: string): Field[] => [
    tenantId,
    conversationId,
    keyId,
    recipientKind,
    recipientRef,
  ],
  share: (tenantId: string, recoveryKeyId: string, index: number, holderRef: string): Field[] => [
    tenantId,
    recoveryKeyId,
    index,
    holderRef,
  ],
  subshare: (tenantId: string, ceremonyId: string, dealerIndex: number, recipientIndex: number): Field[] => [
    tenantId,
    ceremonyId,
    dealerIndex,
    recipientIndex,
  ],
  partial: (
    tenantId: string,
    requestId: string,
    keyId: string,
    holderIndex: number,
    requesterSub: string,
    requesterFingerprint: Bytes
  ): Field[] => [tenantId, requestId, keyId, holderIndex, requesterSub, requesterFingerprint],
};
