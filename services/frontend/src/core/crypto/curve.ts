import { p256 } from '@noble/curves/nist.js';
import { type Bytes, bytes, bytesToBigInt, fromBuffer, randomBytes } from './bytes';

export type Point = InstanceType<typeof p256.Point>;

export const ORDER: bigint = p256.Point.Fn.ORDER;
export const GENERATOR: Point = p256.Point.BASE;
const POINT_BYTES = 65;

export function mod(value: bigint): bigint {
  const reduced = value % ORDER;
  return reduced >= 0n ? reduced : reduced + ORDER;
}

/** SEC1 uncompressed only; the identity has no 65-byte form, so it cannot pass (spec A.1). */
export function decodePoint(raw: ArrayLike<number>): Point {
  if (raw.length !== POINT_BYTES || raw[0] !== 0x04) {
    throw new Error('expected a 65-byte SEC1 uncompressed point');
  }
  const point = p256.Point.fromBytes(bytes(raw));
  point.assertValidity();
  return point;
}

export function encodePoint(point: Point): Bytes {
  if (point.is0()) throw new Error('the identity has no encoding');
  return bytes(point.toBytes(false));
}

/** `scalar·point`, allowing a zero scalar (the result is then the identity). */
export function multiply(point: Point, scalar: bigint): Point {
  const reduced = mod(scalar);
  return reduced === 0n ? p256.Point.ZERO : point.multiply(reduced);
}

export function publicPoint(scalar: bigint): Bytes {
  return encodePoint(multiply(GENERATOR, scalar));
}

/** H_n(m) = int(SHA-512(m)) mod n. */
export async function hashToScalar(message: Bytes): Promise<bigint> {
  return mod(bytesToBigInt(fromBuffer(await crypto.subtle.digest('SHA-512', message))));
}

/** Uniform in [1, n−1]: 48 random bytes reduced, so the bias is negligible. */
export function randomScalar(): bigint {
  return (bytesToBigInt(randomBytes(48)) % (ORDER - 1n)) + 1n;
}
