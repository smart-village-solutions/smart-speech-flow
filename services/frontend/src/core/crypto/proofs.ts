import { type Bytes } from './bytes';
import { GENERATOR, ORDER, type Point, decodePoint, encodePoint, hashToScalar, mod, multiply, publicPoint } from './curve';
import { enc } from './encoding';
import { TAGS } from './tags';

export interface Proof {
  c: bigint;
  s: bigint;
}

function inRange(...scalars: bigint[]): boolean {
  return scalars.every((scalar) => scalar >= 0n && scalar < ORDER);
}

/** s·base + c·pub, or null for the identity. */
function combine(s: bigint, base: Point, c: bigint, pub: Point): Point | null {
  const point = multiply(base, s).add(multiply(pub, c));
  return point.is0() ? null : point;
}

function schnorrChallenge(
  tenantId: string,
  ceremonyId: string,
  dealerIndex: number,
  commitment: Bytes,
  nonce: Bytes
): Promise<bigint> {
  return hashToScalar(enc(TAGS.pok, tenantId, ceremonyId, dealerIndex, commitment, nonce));
}

/** Proof of knowledge of a_j0 behind C_j0 (spec A.8). `nonce` is injected by vector tests only. */
export async function schnorrProve(
  tenantId: string,
  ceremonyId: string,
  dealerIndex: number,
  secret: bigint,
  nonce: bigint
): Promise<Proof> {
  const c = await schnorrChallenge(tenantId, ceremonyId, dealerIndex, publicPoint(secret), publicPoint(nonce));
  return { c, s: mod(nonce - c * secret) };
}

export async function verifySchnorr(
  tenantId: string,
  ceremonyId: string,
  dealerIndex: number,
  commitment: Bytes,
  proof: Readonly<Proof>
): Promise<boolean> {
  if (!inRange(proof.c, proof.s)) return false;
  const nonce = combine(proof.s, GENERATOR, proof.c, decodePoint(commitment));
  if (nonce === null) return false;
  return proof.c === (await schnorrChallenge(tenantId, ceremonyId, dealerIndex, commitment, encodePoint(nonce)));
}

export interface DleqStatement {
  holderShare: Bytes;
  ephemeral: Bytes;
  partial: Bytes;
}

function dleqChallenge(
  scope: readonly [string, string, string, number],
  statement: Readonly<DleqStatement>,
  first: Bytes,
  second: Bytes
): Promise<bigint> {
  return hashToScalar(
    enc(
      TAGS.dleq,
      ...scope,
      encodePoint(GENERATOR),
      statement.holderShare,
      statement.ephemeral,
      statement.partial,
      first,
      second
    )
  );
}

/**
 * Chaum–Pedersen proof that log_G X_i = log_R P_i (spec A.7).
 * `scope` is (tenant_id, request_id, key_id, holder_index).
 */
export async function dleqProve(
  scope: readonly [string, string, string, number],
  share: bigint,
  ephemeral: Bytes,
  nonce: bigint
): Promise<{ partial: Bytes; proof: Proof }> {
  const base = decodePoint(ephemeral);
  const statement = { holderShare: publicPoint(share), ephemeral, partial: encodePoint(multiply(base, share)) };
  const c = await dleqChallenge(scope, statement, publicPoint(nonce), encodePoint(multiply(base, nonce)));
  return { partial: statement.partial, proof: { c, s: mod(nonce - c * share) } };
}

export async function verifyDleq(
  scope: readonly [string, string, string, number],
  statement: Readonly<DleqStatement>,
  proof: Readonly<Proof>
): Promise<boolean> {
  if (!inRange(proof.c, proof.s)) return false;
  const first = combine(proof.s, GENERATOR, proof.c, decodePoint(statement.holderShare));
  const second = combine(proof.s, decodePoint(statement.ephemeral), proof.c, decodePoint(statement.partial));
  if (first === null || second === null) return false;
  return proof.c === (await dleqChallenge(scope, statement, encodePoint(first), encodePoint(second)));
}

/** f(index) for coefficients a_0..a_{k−1}. */
export function evaluatePolynomial(coefficients: readonly bigint[], index: number): bigint {
  return coefficients.reduceRight((total, coefficient) => mod(total * BigInt(index) + coefficient), 0n);
}

export function commitmentsOf(coefficients: readonly bigint[]): Bytes[] {
  return coefficients.map((coefficient) => publicPoint(coefficient));
}

/** Σ_t index^t·C_t, the public image of f(index). */
function commitmentSum(index: number, commitments: readonly Bytes[]): Point {
  let total = multiply(GENERATOR, 0n);
  let power = 1n;
  for (const commitment of commitments) {
    total = total.add(multiply(decodePoint(commitment), power));
    power = mod(power * BigInt(index));
  }
  return total;
}

/** f_j(i)·G == Σ_t i^t·C_jt (spec A.8). */
export function verifySubshare(index: number, subshare: bigint, commitments: readonly Bytes[]): boolean {
  if (subshare <= 0n || subshare >= ORDER) return false;
  return multiply(GENERATOR, subshare).equals(commitmentSum(index, commitments));
}

/** X = Σ_j C_j0. */
export function recoveryPublicKey(dealings: readonly (readonly Bytes[])[]): Bytes {
  return encodePoint(dealings.reduce((total, commitments) => total.add(decodePoint(commitments[0])), multiply(GENERATOR, 0n)));
}

/** X_i = Σ_j Σ_t i^t·C_jt. */
export function holderPublicShare(index: number, dealings: readonly (readonly Bytes[])[]): Bytes {
  return encodePoint(
    dealings.reduce((total, commitments) => total.add(commitmentSum(index, commitments)), multiply(GENERATOR, 0n))
  );
}

function lagrangeAtZero(index: number, indices: readonly number[]): bigint {
  let numerator = 1n;
  let denominator = 1n;
  for (const other of indices) {
    if (other !== index) {
      numerator = mod(numerator * BigInt(other));
      denominator = mod(denominator * BigInt(other - index));
    }
  }
  return mod(numerator * modInverse(denominator));
}

function modInverse(value: bigint): bigint {
  // Fermat: n is prime, so value^(n−2) is the inverse.
  let result = 1n;
  let base = mod(value);
  let exponent = ORDER - 2n;
  while (exponent > 0n) {
    if (exponent & 1n) result = mod(result * base);
    base = mod(base * base);
    exponent >>= 1n;
  }
  return result;
}

/** Σ λ_i·P_i = x·R; returns its x-coordinate, the Z of the recovery wrap (spec A.4). */
export function combinePartials(partials: readonly { index: number; partial: Bytes }[]): Bytes {
  const indices = partials.map((item) => item.index);
  if (new Set(indices).size !== indices.length || indices.some((index) => index <= 0)) {
    throw new Error('partial indices must be distinct and non-zero');
  }
  const total = partials.reduce(
    (sum, item) => sum.add(multiply(decodePoint(item.partial), lagrangeAtZero(item.index, indices))),
    multiply(GENERATOR, 0n)
  );
  return encodePoint(total).slice(1, 33);
}
