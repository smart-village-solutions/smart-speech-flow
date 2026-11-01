import { describe, expect, it } from 'vitest';
import { bytes, utf8 } from '@/core/crypto/bytes';
import { ORDER, decodePoint, encodePoint, publicPoint } from '@/core/crypto/curve';
import { contexts, openWithPrivateKey, openWithSharedX, parseSealed, seal, sealedToJson } from '@/core/crypto/ecies';
import {
  combinePartials,
  commitmentsOf,
  dleqProve,
  evaluatePolynomial,
  schnorrProve,
  verifyDleq,
  verifySchnorr,
  verifySubshare,
} from '@/core/crypto/proofs';
import { signFields, verifyFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';

const sharedXFor = (scalar: bigint, ephemeral: Uint8Array) =>
  encodePoint(decodePoint(ephemeral).multiply(scalar)).slice(1, 33);

describe('archive crypto guards', () => {
  it('refuses a payload presented as another type', async () => {
    const sealed = await seal(TAGS.share, publicPoint(7n), utf8('x'), contexts.share('t', 'k', 2, 'carol'));
    expect(() => parseSealed(sealedToJson(sealed), TAGS.ckWrap)).toThrow();
  });

  it('fails to open a relabelled payload or a swapped context field', async () => {
    const context = contexts.share('t', 'k', 2, 'carol');
    const sealed = await seal(TAGS.share, publicPoint(7n), utf8('x'), context);
    const sharedX = sharedXFor(7n, sealed.ephemeral);
    await expect(openWithSharedX(sealed, sharedX, publicPoint(7n), context)).resolves.toBeDefined();
    await expect(openWithSharedX({ ...sealed, type: TAGS.ckWrap }, sharedX, publicPoint(7n), context)).rejects.toThrow();
    await expect(
      openWithSharedX(sealed, sharedX, publicPoint(7n), contexts.share('t', 'k', 3, 'carol'))
    ).rejects.toThrow();
  });

  it('opens a payload with a non-extractable WebCrypto key', async () => {
    const pair = (await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, [
      'deriveBits',
    ])) as CryptoKeyPair;
    const recipient = bytes(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
    const context = contexts.ckWrap('t', 'c', 'k', 'user', 'alice');
    const sealed = await seal(TAGS.ckWrap, recipient, utf8('ck'), context);
    const opened = await openWithPrivateKey(sealed, pair.privateKey, recipient, context);
    expect(Array.from(opened)).toEqual(Array.from(utf8('ck')));
    await expect(openWithPrivateKey(sealed, pair.privateKey, recipient, contexts.ckWrap('t', 'c', 'k', 'user', 'bob'))).rejects.toThrow();
  });

  it('verifies a signature only under its own tag and fields', async () => {
    const pair = (await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
      'sign',
      'verify',
    ])) as CryptoKeyPair;
    const publicKey = bytes(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
    const signature = await signFields(pair.privateKey, TAGS.wrapSig, ['t', 'c']);
    expect(await verifyFields(publicKey, signature, TAGS.wrapSig, ['t', 'c'])).toBe(true);
    expect(await verifyFields(publicKey, signature, TAGS.chainSig, ['t', 'c'])).toBe(false);
    expect(await verifyFields(publicKey, signature, TAGS.wrapSig, ['t', 'd'])).toBe(false);
    expect(await verifyFields(publicKey, signature.slice(0, 63), TAGS.wrapSig, ['t', 'c'])).toBe(false);
  });

  it('rejects a forged Schnorr proof', async () => {
    const proof = await schnorrProve('t', 'c', 1, 5n, 9n);
    const commitment = publicPoint(5n);
    expect(await verifySchnorr('t', 'c', 1, commitment, proof)).toBe(true);
    expect(await verifySchnorr('t', 'c', 1, commitment, { ...proof, s: (proof.s + 1n) % ORDER })).toBe(false);
    expect(await verifySchnorr('t', 'c', 2, commitment, proof)).toBe(false);
    expect(await verifySchnorr('t', 'c', 1, publicPoint(6n), proof)).toBe(false);
    expect(await verifySchnorr('t', 'c', 1, commitment, { ...proof, s: ORDER })).toBe(false);
  });

  it('rejects a forged partial', async () => {
    const ephemeral = publicPoint(13n);
    const scope = ['t', 'r', 'k', 2] as const;
    const { partial, proof } = await dleqProve(scope, 21n, ephemeral, 4n);
    const statement = { holderShare: publicPoint(21n), ephemeral, partial };
    expect(await verifyDleq(scope, statement, proof)).toBe(true);
    expect(await verifyDleq(scope, { ...statement, partial: publicPoint(99n) }, proof)).toBe(false);
    expect(await verifyDleq(['t', 'r', 'k', 3], statement, proof)).toBe(false);
  });

  it('rejects a subshare inconsistent with its commitments', () => {
    const coefficients = [17n, 23n];
    const commitments = commitmentsOf(coefficients);
    expect(verifySubshare(3, evaluatePolynomial(coefficients, 3), commitments)).toBe(true);
    expect(verifySubshare(3, evaluatePolynomial(coefficients, 3) + 1n, commitments)).toBe(false);
    expect(verifySubshare(3, 0n, commitments)).toBe(false);
  });

  it('does not recover the key from fewer than k partials', async () => {
    // x = 100 shared 2-of-3 by f(i) = 100 + 7i.
    const ephemeral = publicPoint(31n);
    const partialFor = async (index: number) => ({
      index,
      partial: (await dleqProve(['t', 'r', 'k', index], evaluatePolynomial([100n, 7n], index), ephemeral, 3n)).partial,
    });
    const expected = publicPoint((100n * 31n) % ORDER).slice(1, 33);
    expect(Array.from(combinePartials([await partialFor(1), await partialFor(3)]))).toEqual(Array.from(expected));
    expect(Array.from(combinePartials([await partialFor(1)]))).not.toEqual(Array.from(expected));
    expect(() => combinePartials([{ index: 1, partial: ephemeral }, { index: 1, partial: ephemeral }])).toThrow();
  });
});
