/**
 * Byte helpers for the archive crypto.
 *
 * WebCrypto wants `Uint8Array<ArrayBuffer>`, and under vitest the global
 * typed arrays come from another realm than Node's WebCrypto results, so every
 * value is normalised through `bytes()` and compared by content, never by
 * `instanceof`.
 */
export type Bytes = Uint8Array<ArrayBuffer>;

export function bytes(source: ArrayLike<number>): Bytes {
  return Uint8Array.from(source);
}

/** A WebCrypto result, copied into this realm's typed array. */
export function fromBuffer(buffer: ArrayBuffer): Bytes {
  return Uint8Array.from(new Uint8Array(buffer));
}

export function utf8(text: string): Bytes {
  return bytes(new TextEncoder().encode(text));
}

export function concat(...parts: readonly ArrayLike<number>[]): Bytes {
  const out = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(Array.from(part), offset);
    offset += part.length;
  }
  return out;
}

export function equalBytes(left: ArrayLike<number>, right: ArrayLike<number>): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left[index] ^ right[index];
  }
  return difference === 0;
}

export function toBase64Url(data: ArrayLike<number>): string {
  const binary = Array.from(data, (byte) => String.fromCodePoint(byte)).join('');
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

const BASE64URL = /^[A-Za-z0-9_-]*$/;

/** Strict: the URL-safe alphabet without padding, nothing else. */
export function fromBase64Url(text: string): Bytes {
  if (!BASE64URL.test(text) || text.length % 4 === 1) {
    throw new Error('not unpadded base64url');
  }
  const binary = atob(text.replaceAll('-', '+').replaceAll('_', '/'));
  return bytes(Array.from(binary, (character) => character.codePointAt(0) ?? 0));
}

export function toHex(data: ArrayLike<number>): string {
  return Array.from(data, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function scalarToBytes(value: bigint): Bytes {
  return bytes(Array.from({ length: 32 }, (_, index) => Number((value >> BigInt(8 * (31 - index))) & 0xffn)));
}

export function bytesToBigInt(data: ArrayLike<number>): bigint {
  return Array.from(data).reduce((total, byte) => (total << 8n) | BigInt(byte), 0n);
}

export function randomBytes(length: number): Bytes {
  return crypto.getRandomValues(new Uint8Array(length));
}
