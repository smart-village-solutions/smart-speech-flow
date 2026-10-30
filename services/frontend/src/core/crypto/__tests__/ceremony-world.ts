import { type Bytes, fromBuffer } from '@/core/crypto/bytes';
import type {
  CeremonyFacts,
  CeremonyParticipant,
  NewDealing,
  TrustChain,
} from '@/core/crypto/ceremony-crypto.port';
import { publicPoint } from '@/core/crypto/curve';
import { holderPublicShare, recoveryPublicKey } from '@/core/crypto/proofs';
import { signFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { fingerprint, transcriptHash } from '@/core/crypto/transcript';
import { createWebCeremonyCrypto } from '@/core/crypto/web-ceremony-crypto';

/** A first ceremony dealt in this browser: what the ceremony and resharing tests start from. */
export const TENANT = 'tenant-kassel';
export const CEREMONY = '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a';
export const ceremonyCrypto = createWebCeremonyCrypto();

export interface Custodian {
  participant: CeremonyParticipant;
  encPrivate: CryptoKey;
  sigPrivate: CryptoKey;
}

export async function custodian(index: number): Promise<Custodian> {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, [
    'deriveBits',
  ]);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
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

export async function setUp() {
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
  for (const c of custodians)
    dealt.push(await ceremonyCrypto.deal(facts, c.participant.holderIndex, c.sigPrivate));
  const published: CeremonyFacts = {
    ...facts,
    dealings: dealt.map((d, i) => ({
      dealerIndex: i + 1,
      commitments: d.commitments,
      proof: d.proof,
      signature: d.signature,
    })),
  };
  // What the gateway serves each holder: every dealer's sub-share for that holder's index.
  const subsharesFor = (...indices: number[]) =>
    new Map(
      indices.map((index) => [
        index,
        new Map(dealt.map((d, i) => [i + 1, d.subshares.get(index) ?? ''])),
      ])
    );
  return { custodians, device, published, dealt, subsharesFor };
}

/** The transcript as the gateway computes it from the same published facts. */
export function transcriptOf(world: Awaited<ReturnType<typeof setUp>>): Promise<Bytes> {
  const { published } = world;
  const lists = published.dealings.map((d) => d.commitments);
  return transcriptHash({
    tenantId: TENANT,
    ceremonyId: CEREMONY,
    k: 2,
    participants: published.participants.map((p) => ({
      holderRef: p.holderRef,
      index: p.holderIndex,
      fingerprint: p.fingerprint,
    })),
    dealings: published.dealings,
    recoveryPublicKey: recoveryPublicKey(lists),
    holderShares: published.participants.map((p) => holderPublicShare(p.holderIndex, lists)),
    gatewayKeys: published.gatewayKeys,
  });
}

/** A closed ceremony as the archive serves it: every custodian signed its transcript. */
export async function signedCeremony() {
  const world = await setUp();
  const hash = await transcriptOf(world);
  const signatures = new Map<number, Bytes>();
  for (const c of world.custodians) {
    signatures.set(
      c.participant.holderIndex,
      await signFields(c.sigPrivate, TAGS.transcript, [hash])
    );
  }
  return { facts: world.published, hash, signatures, world };
}

/** One generation, as the trust route serves a key that was never reshared. */
export function chainOf(
  facts: CeremonyFacts,
  hash: Bytes,
  signatures: Map<number, Bytes>
): TrustChain {
  return {
    recoveryKeyId: facts.ceremonyId,
    firstTranscriptHash: hash,
    holdersCeremonyId: facts.ceremonyId,
    holdersTranscriptHash: hash,
    generations: [{ facts, transcriptHash: hash, signatures }],
  };
}
