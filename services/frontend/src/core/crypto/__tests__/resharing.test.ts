import { describe, expect, it } from 'vitest';
import { type Bytes, bytesToBigInt, equalBytes } from '@/core/crypto/bytes';
import { contexts, openWithPrivateKey, parseSealed } from '@/core/crypto/ecies';
import {
  type CeremonyFacts,
  type CertifiedTrust,
  type Generation,
  type NewDealing,
  ShareMismatchError,
  type TrustChain,
} from '@/core/crypto/ceremony-crypto.port';
import { GENERATOR, encodePoint, mod, multiply, randomScalar } from '@/core/crypto/curve';
import {
  commitmentsOf,
  lagrangeAtZero,
  schnorrProve,
  verifyShareProof,
} from '@/core/crypto/proofs';
import { transcriptOf } from '@/core/crypto/ceremony-checks';
import { signFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { transcriptHash } from '@/core/crypto/transcript';
import {
  CEREMONY,
  TENANT,
  type Custodian,
  ceremonyCrypto,
  chainOf,
  custodian,
  signedCeremony,
} from './ceremony-world';

const RESHARING = '7e6d5c4b-3a29-4180-9f7e-6d5c4b3a2918';

/** Every first-generation share, custodians 1–3 and paper sheets 4–5, as their holders hold them. */
async function firstGeneration() {
  const { facts, hash, signatures, world } = await signedCeremony();
  const shares = new Map<number, bigint>();
  for (const c of world.custodians) {
    const index = c.participant.holderIndex;
    const receiver = { privateKey: c.encPrivate, publicKey: c.participant.encPub };
    const received = await ceremonyCrypto.receive(facts, receiver, world.subsharesFor(index), hash);
    shares.set(index, received.shares.get(index) ?? 0n);
  }
  const paper = await ceremonyCrypto.receive(facts, world.device, world.subsharesFor(4, 5), hash);
  for (const [index, share] of paper.shares) shares.set(index, share);
  const first = chainOf(facts, hash, signatures);
  return {
    first,
    previous: await ceremonyCrypto.certifyChain(first),
    shares,
    custodians: world.custodians,
  };
}

async function resharingFacts(previous: CertifiedTrust, dealers = [1, 4]) {
  const holders = [await custodian(1), await custodian(2), await custodian(3)];
  const facts: CeremonyFacts = {
    tenantId: TENANT,
    ceremonyId: RESHARING,
    k: 2,
    participants: holders.map((h) => h.participant),
    dealings: [],
    gatewayKeys: [{ keyId: 'gk-2', publicKey: encodePoint(multiply(GENERATOR, 98n)) }],
    resharing: {
      recoveryKeyId: CEREMONY,
      previousTranscript: previous.holdersTranscriptHash,
      dealers,
      previous,
    },
  };
  return { facts, holders };
}

function published(facts: CeremonyFacts, dealt: Map<number, NewDealing>): CeremonyFacts {
  return {
    ...facts,
    dealings: [...dealt].map(([dealerIndex, d]) => ({
      dealerIndex,
      commitments: d.commitments,
      proof: d.proof,
      signature: d.signature,
    })),
  };
}

/** Custodian 1 deals its share and the device types in sheet 4; then the new holders confirm. */
async function wholeResharing() {
  const generation = await firstGeneration();
  const { facts, holders } = await resharingFacts(generation.previous);
  const dealt = new Map<number, NewDealing>([
    [
      1,
      await ceremonyCrypto.dealShare(
        facts,
        1,
        generation.shares.get(1) ?? 0n,
        generation.custodians[0].sigPrivate
      ),
    ],
    [4, await ceremonyCrypto.dealShare(facts, 4, generation.shares.get(4) ?? 0n, null)],
  ]);
  return { ...generation, facts: published(facts, dealt), holders, dealt };
}

/** What the gateway serves one new holder: its sub-share from each dealer. */
function received(holder: Readonly<Custodian>, dealt: Map<number, NewDealing>) {
  const index = holder.participant.holderIndex;
  const subshares = new Map([
    [index, new Map([...dealt].map(([dealer, d]) => [dealer, d.subshares.get(index) ?? '']))],
  ]);
  const receiver = { privateKey: holder.encPrivate, publicKey: holder.participant.encPub };
  return { index, receiver, subshares };
}

/** What the gateway computes: the dealt facts' transcript, with the previous hash filled in. */
function gatewayTranscript(facts: CeremonyFacts): Promise<Bytes> {
  return transcriptHash(transcriptOf(facts));
}

async function confirmedChain() {
  const r = await wholeResharing();
  const signatures = new Map<number, Bytes>();
  const newShares = new Map<number, bigint>();
  let transcript: Bytes = new Uint8Array(0);
  for (const holder of r.holders) {
    const { index, receiver, subshares } = received(holder, r.dealt);
    const facts = r.facts;
    const probe = await ceremonyCrypto.receive(
      facts,
      receiver,
      subshares,
      await gatewayTranscript(facts)
    );
    transcript = probe.transcriptHash;
    const share = probe.shares.get(index) ?? 0n;
    newShares.set(index, share);
    const confirmation = await ceremonyCrypto.confirm(
      facts,
      holder.participant,
      share,
      transcript,
      holder.sigPrivate,
      receiver
    );
    signatures.set(index, confirmation.transcriptSignature);
    expect(confirmation.shareProof).not.toBeNull();
  }
  const second: Generation = {
    facts: {
      ...r.facts,
      resharing: {
        ...(r.facts.resharing as NonNullable<CeremonyFacts['resharing']>),
        previous: null,
      },
    },
    transcriptHash: transcript,
    signatures,
  };
  const chain: TrustChain = {
    ...r.first,
    holdersCeremonyId: RESHARING,
    holdersTranscriptHash: transcript,
    generations: [...r.first.generations, second],
  };
  return { ...r, chain, newShares, transcript };
}

describe('resharing in the browser (spec §9.7)', () => {
  it('moves the shares to new holders, keeps X, and certifies the chain', async () => {
    const r = await confirmedChain();
    const trust = await ceremonyCrypto.certifyChain(r.chain);
    expect(trust.recoveryKeyId).toBe(CEREMONY);
    expect(trust.holdersCeremonyId).toBe(RESHARING);
    expect(equalBytes(trust.transcriptHash, r.first.firstTranscriptHash)).toBe(true);
    expect(equalBytes(trust.holdersTranscriptHash, r.transcript)).toBe(true);
    expect(equalBytes(trust.recoveryPublicKey, r.previous.recoveryPublicKey)).toBe(true);
    expect([...trust.gatewayKeys.keys()].sort((a, b) => a.localeCompare(b))).toEqual([
      'gk-1',
      'gk-2',
    ]);
    // Any two new shares rebuild x: Σ λ'_j·x'_j·G is X.
    const pair = [1, 3];
    const rebuilt = pair.reduce(
      (total, index) => mod(total + lagrangeAtZero(index, pair) * (r.newShares.get(index) ?? 0n)),
      0n
    );
    expect(equalBytes(encodePoint(multiply(GENERATOR, rebuilt)), trust.recoveryPublicKey)).toBe(
      true
    );
  });

  it('proves each new share from the blob it stored', async () => {
    const r = await wholeResharing();
    const holder = r.holders[1];
    const { index, receiver, subshares } = received(holder, r.dealt);
    const hash = await gatewayTranscript(r.facts);
    const got = await ceremonyCrypto.receive(r.facts, receiver, subshares, hash);
    const share = got.shares.get(index) ?? 0n;
    const confirmation = await ceremonyCrypto.confirm(
      r.facts,
      holder.participant,
      share,
      hash,
      holder.sigPrivate,
      receiver
    );
    const publicShare = encodePoint(multiply(GENERATOR, share));
    const proof = confirmation.shareProof ?? { c: 0n, s: 0n };
    expect(await verifyShareProof(TENANT, RESHARING, index, publicShare, proof)).toBe(true);
    expect(await verifyShareProof(TENANT, RESHARING, index + 1, publicShare, proof)).toBe(false);
    // Sealed under the key's ID, which approvals open it with, never the resharing's.
    const context = contexts.share(TENANT, CEREMONY, index, holder.participant.holderRef);
    const sealed = parseSealed(confirmation.encryptedShare, TAGS.share);
    const opened = await openWithPrivateKey(
      sealed,
      holder.encPrivate,
      holder.participant.encPub,
      context
    );
    expect(bytesToBigInt(opened)).toBe(share);
  });

  it('refuses a typed sheet that is not the share the generation lists, without a fault', async () => {
    const generation = await firstGeneration();
    const { facts } = await resharingFacts(generation.previous);
    await expect(
      ceremonyCrypto.dealShare(facts, 4, (generation.shares.get(4) ?? 0n) + 1n, null)
    ).rejects.toBeInstanceOf(ShareMismatchError);
  });

  it('opens a custodian dealer’s own share under the key’s ID', async () => {
    const generation = await firstGeneration();
    const { facts } = await resharingFacts(generation.previous);
    const c = generation.custodians[0];
    const sealed = await ceremonyCrypto.confirm(
      { ...facts, ceremonyId: CEREMONY, resharing: undefined },
      c.participant,
      generation.shares.get(1) ?? 0n,
      new Uint8Array(32),
      c.sigPrivate,
      { privateKey: c.encPrivate, publicKey: c.participant.encPub }
    );
    const receiver = { privateKey: c.encPrivate, publicKey: c.participant.encPub };
    const share = await ceremonyCrypto.openShare(
      facts,
      c.participant,
      sealed.encryptedShare,
      receiver
    );
    expect(share).toBe(generation.shares.get(1));
  });

  it('aborts on a contribution that is not λ_i·X_i, though its proof holds', async () => {
    const r = await wholeResharing();
    const secret = randomScalar();
    const commitments = commitmentsOf([secret, randomScalar()]);
    const proof = await schnorrProve(TENANT, RESHARING, 1, secret, randomScalar());
    const forged = {
      ...r.facts,
      dealings: r.facts.dealings.map((d) =>
        d.dealerIndex === 1 ? { ...d, commitments, proof } : d
      ),
    };
    const { receiver, subshares } = received(r.holders[0], r.dealt);
    await expect(
      ceremonyCrypto.receive(forged, receiver, subshares, new Uint8Array(32))
    ).rejects.toMatchObject({
      fault: 'contribution_invalid',
    });
  });

  it('refuses a dealing signed over another holder set', async () => {
    const generation = await firstGeneration();
    const { facts } = await resharingFacts(generation.previous);
    const other = { ...facts, participants: facts.participants.slice(0, 2) };
    const share = generation.shares.get(1) ?? 0n;
    const dealing = await ceremonyCrypto.dealShare(
      facts,
      1,
      share,
      generation.custodians[0].sigPrivate
    );
    const elsewhere = await ceremonyCrypto.dealShare(
      other,
      1,
      share,
      generation.custodians[0].sigPrivate
    );
    const sheet = await ceremonyCrypto.dealShare(facts, 4, generation.shares.get(4) ?? 0n, null);
    const forged = published(
      facts,
      new Map([
        [1, { ...dealing, signature: elsewhere.signature }],
        [4, sheet],
      ])
    );
    const holder = forged.participants[0];
    await expect(
      ceremonyCrypto.receive(
        forged,
        { privateKey: (await custodian(9)).encPrivate, publicKey: holder.encPub },
        new Map(),
        new Uint8Array(32)
      )
    ).rejects.toMatchObject({ fault: 'signature_invalid' });
  });

  it('refuses a chain whose link names another generation, or a dealer outside it', async () => {
    const r = await confirmedChain();
    const [first, second] = r.chain.generations;
    const resharing = second.facts.resharing as NonNullable<CeremonyFacts['resharing']>;
    const unlinked = {
      ...r.chain,
      generations: [
        first,
        {
          ...second,
          facts: {
            ...second.facts,
            resharing: { ...resharing, previousTranscript: new Uint8Array(32) },
          },
        },
      ],
    };
    await expect(ceremonyCrypto.certifyChain(unlinked)).rejects.toMatchObject({
      fault: 'chain_invalid',
    });
    const outsider = {
      ...r.chain,
      generations: [
        first,
        { ...second, facts: { ...second.facts, resharing: { ...resharing, dealers: [1, 9] } } },
      ],
    };
    await expect(ceremonyCrypto.certifyChain(outsider)).rejects.toMatchObject({
      fault: 'chain_invalid',
    });
    const reordered = { ...r.chain, generations: [second, first] };
    await expect(ceremonyCrypto.certifyChain(reordered)).rejects.toMatchObject({
      fault: 'chain_invalid',
    });
  });

  it('refuses a chain that names another key than its first ceremony', async () => {
    const generation = await firstGeneration();
    await expect(
      ceremonyCrypto.certifyChain({ ...generation.first, recoveryKeyId: 'another-key' })
    ).rejects.toMatchObject({ fault: 'chain_invalid' });
  });

  it('refuses to deal or open when the served resharing names another key or generation', async () => {
    const generation = await firstGeneration();
    const { facts } = await resharingFacts(generation.previous);
    const share = generation.shares.get(1) ?? 0n;
    const resharing = facts.resharing as NonNullable<CeremonyFacts['resharing']>;
    for (const served of [
      { ...resharing, recoveryKeyId: RESHARING },
      { ...resharing, previousTranscript: new Uint8Array(32) },
    ]) {
      await expect(
        ceremonyCrypto.dealShare({ ...facts, resharing: served }, 1, share, null)
      ).rejects.toMatchObject({
        fault: 'chain_invalid',
      });
    }
  });

  it('refuses a chain cut short of the holders the key names', async () => {
    const r = await confirmedChain();
    const truncated = { ...r.chain, generations: r.chain.generations.slice(0, 1) };
    await expect(ceremonyCrypto.certifyChain(truncated)).rejects.toMatchObject({
      fault: 'chain_invalid',
    });
  });

  it('refuses a chain whose new custodian did not sign', async () => {
    const r = await confirmedChain();
    const [first, second] = r.chain.generations;
    const missing = new Map(second.signatures);
    missing.delete(2);
    const unsigned = { ...r.chain, generations: [first, { ...second, signatures: missing }] };
    await expect(ceremonyCrypto.certifyChain(unsigned)).rejects.toMatchObject({
      fault: 'signature_invalid',
    });
  });

  it('refuses a dealing a custodian dealer did not sign with its own key', async () => {
    const r = await confirmedChain();
    const [first, second] = r.chain.generations;
    const intruder = await custodian(1);
    const signature = await signFields(intruder.sigPrivate, TAGS.reshareDealingSig, [
      new Uint8Array(1),
    ]);
    const dealings = second.facts.dealings.map((d) =>
      d.dealerIndex === 1 ? { ...d, signature } : d
    );
    const resigned = {
      ...r.chain,
      generations: [first, { ...second, facts: { ...second.facts, dealings } }],
    };
    await expect(ceremonyCrypto.certifyChain(resigned)).rejects.toMatchObject({
      fault: 'signature_invalid',
    });
  });
});
