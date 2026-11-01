import { type Bytes, concat, fromBuffer, randomBytes } from './bytes';
import { enc } from './encoding';
import { TAGS } from './tags';

const NONCE_BYTES = 12;
const VERSION = 1;

/** One message for every failure: which check failed is nobody's business. */
class EnvelopeError extends Error {
  constructor() {
    super('envelope failed authentication');
    this.name = 'EnvelopeError';
  }
}

export function aesKey(raw: Bytes): Promise<CryptoKey> {
  return crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt']);
}

export async function aesEncrypt(key: CryptoKey, nonce: Bytes, plaintext: Bytes, aad: Bytes): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: aad }, key, plaintext));
}

export async function aesDecrypt(key: CryptoKey, nonce: Bytes, ciphertext: Bytes, aad: Bytes): Promise<Bytes> {
  try {
    return fromBuffer(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce, additionalData: aad }, key, ciphertext));
  } catch {
    throw new EnvelopeError();
  }
}

export interface ObjectAddress {
  tenantId: string;
  conversationId: string;
  entryId: string;
  objectType: string;
  keyId: string;
}

/** Associated data of an archive object (spec A.3). */
export function objectAad(address: Readonly<ObjectAddress>): Bytes {
  return enc(TAGS.object, address.tenantId, address.conversationId, address.entryId, address.objectType, address.keyId);
}

/** `0x01 || nonce || ciphertext || tag`. `nonce` is injected by the vector tests only. */
export async function sealEnvelope(key: CryptoKey, plaintext: Bytes, aad: Bytes, nonce?: Bytes): Promise<Bytes> {
  const iv = nonce ?? randomBytes(NONCE_BYTES);
  return concat([VERSION], iv, await aesEncrypt(key, iv, plaintext, aad));
}

export function openEnvelope(key: CryptoKey, envelope: Bytes, aad: Bytes): Promise<Bytes> {
  if (envelope.length < 1 + NONCE_BYTES + 16 || envelope[0] !== VERSION) {
    return Promise.reject(new EnvelopeError());
  }
  return aesDecrypt(key, envelope.slice(1, 1 + NONCE_BYTES), envelope.slice(1 + NONCE_BYTES), aad);
}
