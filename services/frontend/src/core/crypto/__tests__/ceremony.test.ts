import { describe, expect, it } from 'vitest';
import { type Bytes, equalBytes, fromBuffer, scalarToBytes } from '@/core/crypto/bytes';
import { contexts, seal, sealedToJson } from '@/core/crypto/ecies';
import { TAGS } from '@/core/crypto/tags';
import {
  type CeremonyFacts,
  type CeremonyParticipant,
  type NewDealing,
} from '@/core/crypto/ceremony-crypto.port';
import { GENERATOR, ORDER, decodePoint, encodePoint, mod, multiply, publicPoint } from '@/core/crypto/curve';
import { combinePartials, holderPublicShare, recoveryPublicKey } from '@/core/crypto/proofs';
import { fingerprint, transcriptHash } from '@/core/crypto/transcript';
import { createWebCeremonyCrypto } from '@/core/crypto/web-ceremony-crypto';

const TENANT = 'tenant-kassel';
const CEREMONY = '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a';
const ceremonyCrypto = createWebCeremonyCrypto();

interface Custodian {
  participant: CeremonyParticipant;
  encPrivate: CryptoKey;
  sigPrivate: CryptoKey;
}

async function custodian(index: number): Promise<Custodian> {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
  const encPub = fromBuffer(await crypto.subtle.exportKey('raw', enc.publicKey));
  const sigPub = fromBuffer(await crypto.subtle.exportKey('raw', sig.publicKey));
  const holderRef = `custodian-${index}`;
  return {
    participant: {
      holderIndex: index,
      holderRef,
      kind: 'custodian',
      displayName: holderRef,
      encPub,
      sigPub,
      fingerprint: await fingerprint(TENANT, holderRef, encPub, sigPub),
    },
    encPrivate: enc.privateKey,
    sigPrivate: sig.privateKey,
  };
}

async function setUp() {
  const custodians = [await custodian(1), await custodian(2), await custodian(3)];
  const device = await ceremonyCrypto.createPaperDevice(TENANT);
  const paper: CeremonyParticipant[] = [4, 5].map((index) => ({
    holderIndex: index,
    holderRef: `paper-${index - 3}`,
    kind: 'paper',
    displayName: null,
    encPub: device.publicKey,
    sigPub: null,
    fingerprint: device.fingerprint,
  }));
  const facts: CeremonyFacts = {
    tenantId: TENANT,
    ceremonyId: CEREMONY,
    k: 2,
    participants: [...custodians.map((c) => c.participant), ...paper],
    dealings: [],
    gatewayKeys: [{ keyId: 'gk-1', publicKey: publicPoint(99n) }],
  };
  const dealt: NewDealing[] = [];
  for (const c of custodians) dealt.push(await ceremonyCrypto.deal(facts, c.participant.holderIndex, c.sigPrivate));
  const published: CeremonyFacts = {
    ...facts,
    dealings: dealt.map((d, i) => ({ dealerIndex: i + 1, commitments: d.commitments, proof: d.proof, signature: d.signature })),
  };
  // What the gateway serves each holder: every dealer's sub-share for that holder's index.
  const subsharesFor = (...indices: number[]) =>
    new Map(indices.map((index) => [index, new Map(dealt.map((d, i) => [i + 1, d.subshares.get(index) ?? '']))]));
  return { custodians, device, published, dealt, subsharesFor };
}

/** The transcript as the gateway computes it from the same published facts. */
function transcriptOf(world: Awaited<ReturnType<typeof setUp>>): Promise<Bytes> {
  const { published } = world;
  const lists = published.dealings.map((d) => d.commitments);
  return transcriptHash({
    tenantId: TENANT,
    ceremonyId: CEREMONY,
    k: 2,
    participants: published.participants.map((p) => ({ holderRef: p.holderRef, index: p.holderIndex, fingerprint: p.fingerprint })),
    dealings: published.dealings,
    recoveryPublicKey: recoveryPublicKey(lists),
    holderShares: published.participants.map((p) => holderPublicShare(p.holderIndex, lists)),
    gatewayKeys: published.gatewayKeys,
  });
}

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
