import { describe, expect, it } from 'vitest';
import { equalBytes, scalarToBytes } from '@/core/crypto/bytes';
import { contexts, seal, sealedToJson } from '@/core/crypto/ecies';
import { TAGS } from '@/core/crypto/tags';
import { GENERATOR, ORDER, decodePoint, encodePoint, mod, multiply, publicPoint } from '@/core/crypto/curve';
import { combinePartials, holderPublicShare, recoveryPublicKey } from '@/core/crypto/proofs';
import { CEREMONY, TENANT, ceremonyCrypto, chainOf, setUp, signedCeremony, transcriptOf } from './ceremony-world';

function lagrange(index: number, indices: number[]): bigint {
  let numerator = 1n;
  let denominator = 1n;
  for (const other of indices) {
    if (other !== index) {
      numerator = mod(numerator * BigInt(other));
      denominator = mod(denominator * BigInt(other - index));
    }
  }
  // Test-only: Fermat inverse by exponentiation.
  let inverse = 1n;
  let base = denominator;
  let exponent = ORDER - 2n;
  while (exponent > 0n) {
    if (exponent & 1n) inverse = mod(inverse * base);
    base = mod(base * base);
    exponent >>= 1n;
  }
  return mod(numerator * inverse);
}

describe('recovery-key ceremony in the browser', () => {
  it('gives every holder a share of one key that no party ever held', async () => {
    const world = await setUp();
    const transcript = await transcriptOf(world);
    const shares = new Map<number, bigint>();
    for (const c of world.custodians) {
      const index = c.participant.holderIndex;
      const received = await ceremonyCrypto.receive(
        world.published,
        { privateKey: c.encPrivate, publicKey: c.participant.encPub },
        world.subsharesFor(index),
        transcript
      );
      expect(equalBytes(received.transcriptHash, transcript)).toBe(true);
      shares.set(index, received.shares.get(index) ?? 0n);
    }
    const paper = await ceremonyCrypto.receive(world.published, world.device, world.subsharesFor(4, 5), transcript);
    for (const [index, share] of paper.shares) shares.set(index, share);

    // Test-only reconstruction: any two shares, custodian or paper, give the same x behind X.
    const secrets = [
      [1, 2],
      [3, 4],
      [4, 5],
    ].map((pair) => mod(pair.reduce((sum, i) => sum + lagrange(i, pair) * (shares.get(i) ?? 0n), 0n)));
    expect(new Set(secrets).size).toBe(1);
    const X = recoveryPublicKey(world.published.dealings.map((d) => d.commitments));
    expect(equalBytes(publicPoint(secrets[0]), X)).toBe(true);
    // k partials x_i·R combine to x·R, as a recovery will (spec §9.3).
    const r = 12345n;
    const R = multiply(GENERATOR, r);
    const z = combinePartials([1, 3].map((index) => ({ index, partial: encodePoint(multiply(R, shares.get(index) ?? 0n)) })));
    expect(equalBytes(z, encodePoint(multiply(decodePoint(X), r)).slice(1, 33))).toBe(true);
  });

  it('seals the share for its holder and signs the transcript', async () => {
    const world = await setUp();
    const c = world.custodians[0];
    const confirmation = await ceremonyCrypto.confirm(world.published, c.participant, 7n, new Uint8Array(32).fill(1), c.sigPrivate);
    expect(JSON.parse(confirmation.encryptedShare).t).toBe('ssf-rec/share/v1');
    expect(confirmation.transcriptSignature).toHaveLength(64);
  });

  it.each([
    ['a forged proof', 'proof_invalid', (w: Awaited<ReturnType<typeof setUp>>) => {
      w.published.dealings[0] = { ...w.published.dealings[0], proof: { ...w.published.dealings[0].proof, s: w.published.dealings[0].proof.s + 1n } };
    }],
    ['a dealing signed by someone else', 'signature_invalid', (w: Awaited<ReturnType<typeof setUp>>) => {
      w.published.dealings[0] = { ...w.published.dealings[0], signature: w.published.dealings[1].signature };
    }],
    ['a withheld dealing', 'transcript_mismatch', (w: Awaited<ReturnType<typeof setUp>>) => {
      w.published.dealings.pop();
    }],
    ['a substituted key', 'fingerprint_mismatch', (w: Awaited<ReturnType<typeof setUp>>) => {
      w.published.participants[1] = { ...w.published.participants[1], encPub: w.published.participants[2].encPub };
    }],
  ])('refuses %s', async (_label, fault, tamper) => {
    const world = await setUp();
    // The transcript the gateway computed before anything was tampered with.
    const transcript = await transcriptOf(world);
    tamper(world);
    const c = world.custodians[0];
    await expect(
      ceremonyCrypto.receive(world.published, { privateKey: c.encPrivate, publicKey: c.participant.encPub }, world.subsharesFor(1), transcript)
    ).rejects.toMatchObject({ fault });
  });

  it('refuses a sub-share that opens but does not match its commitments', async () => {
    const world = await setUp();
    const transcript = await transcriptOf(world);
    const c = world.custodians[0];
    const received = world.subsharesFor(1);
    // Dealer 1 seals a value off its polynomial, correctly, for holder 1.
    const wrong = await seal(TAGS.subshare, c.participant.encPub, scalarToBytes(12345n), contexts.subshare(TENANT, CEREMONY, 1, 1));
    received.get(1)?.set(1, sealedToJson(wrong));
    await expect(
      ceremonyCrypto.receive(world.published, { privateKey: c.encPrivate, publicKey: c.participant.encPub }, received, transcript)
    ).rejects.toMatchObject({ fault: 'subshare_invalid' });
  });

  it('refuses a transcript other than the one the gateway will sign', async () => {
    const world = await setUp();
    const c = world.custodians[0];
    await expect(
      ceremonyCrypto.receive(world.published, { privateKey: c.encPrivate, publicKey: c.participant.encPub }, world.subsharesFor(1), new Uint8Array(32))
    ).rejects.toMatchObject({ fault: 'transcript_mismatch' });
  });
});

describe('certify', () => {
  it('certifies the facts a recovery needs: k, X and every X_i from the commitments', async () => {
    const { facts, hash, signatures } = await signedCeremony();
    const trust = await ceremonyCrypto.certifyChain(chainOf(facts, hash, signatures));
    const lists = [...facts.dealings]
      .sort((left, right) => left.dealerIndex - right.dealerIndex)
      .map((dealing) => dealing.commitments);
    expect(trust.recoveryKeyId).toBe(facts.ceremonyId);
    expect(trust.k).toBe(facts.k);
    expect(equalBytes(trust.transcriptHash, hash)).toBe(true);
    expect(equalBytes(trust.recoveryPublicKey, recoveryPublicKey(lists))).toBe(true);
    for (const participant of facts.participants) {
      const share = trust.holderShares.get(participant.holderIndex) ?? new Uint8Array(0);
      expect(equalBytes(share, holderPublicShare(participant.holderIndex, lists))).toBe(true);
    }
    expect([...trust.gatewayKeys.keys()]).toEqual(['gk-1']);
  });

  it('returns the gateway keys a fully signed transcript lists', async () => {
    const { facts, hash, signatures } = await signedCeremony();
    const keys = (await ceremonyCrypto.certifyChain(chainOf(facts, hash, signatures))).gatewayKeys;
    expect([...keys.keys()]).toEqual(['gk-1']);
    expect(equalBytes(keys.get('gk-1') ?? new Uint8Array(0), publicPoint(99n))).toBe(true);
  });

  it('refuses a custodian whose signing key does not match its fingerprint', async () => {
    const { facts, hash, signatures } = await signedCeremony();
    const [first, second, ...rest] = facts.participants;
    const swapped = {
      ...facts,
      participants: [{ ...first, sigPub: second.sigPub }, second, ...rest],
    };
    await expect(ceremonyCrypto.certifyChain(chainOf(swapped, hash, signatures))).rejects.toMatchObject({
      fault: 'fingerprint_mismatch',
    });
  });

  it('refuses a missing or foreign custodian signature', async () => {
    const { facts, hash, signatures } = await signedCeremony();
    const missing = new Map(signatures);
    missing.delete(2);
    await expect(ceremonyCrypto.certifyChain(chainOf(facts, hash, missing))).rejects.toMatchObject({
      fault: 'signature_invalid',
    });
    const foreign = new Map(signatures);
    foreign.set(2, signatures.get(1) ?? new Uint8Array(64));
    await expect(ceremonyCrypto.certifyChain(chainOf(facts, hash, foreign))).rejects.toMatchObject({
      fault: 'signature_invalid',
    });
  });

  it('refuses custodians relabelled as paper holders, whose signatures would then be skipped', async () => {
    const { facts, hash } = await signedCeremony();
    const relabelled = {
      ...facts,
      participants: facts.participants.map((p) => ({ ...p, kind: 'paper' as const })),
    };
    await expect(ceremonyCrypto.certifyChain(chainOf(relabelled, hash, new Map()))).rejects.toMatchObject({
      fault: 'signature_invalid',
    });
  });

  it('refuses a transcript other than the recovery key’s', async () => {
    const { facts, hash, signatures } = await signedCeremony();
    await expect(
      ceremonyCrypto.certifyChain(chainOf(facts, new Uint8Array(32), signatures))
    ).rejects.toMatchObject({
      fault: 'transcript_mismatch',
    });
    const moreKeys = {
      ...facts,
      gatewayKeys: [...facts.gatewayKeys, { keyId: 'gk-2', publicKey: publicPoint(7n) }],
    };
    await expect(ceremonyCrypto.certifyChain(chainOf(moreKeys, hash, signatures))).rejects.toMatchObject({
      fault: 'transcript_mismatch',
    });
  });
});
