import { type Bytes, bytesToBigInt, equalBytes, fromBuffer, scalarToBytes } from './bytes';
import {
  type CeremonyCrypto,
  type CeremonyFacts,
  type CertifiedTrust,
  type CeremonyFault,
  type CeremonyParticipant,
  CeremonyCheckError,
  type PublishedDealing,
  type Receiver,
} from './ceremony-crypto.port';
import { mod, randomScalar } from './curve';
import { contexts, openWithPrivateKey, parseSealed, seal, sealedToJson } from './ecies';
import {
  commitmentsOf,
  evaluatePolynomial,
  holderPublicShare,
  recoveryPublicKey,
  schnorrProve,
  verifySchnorr,
  verifySubshare,
} from './proofs';
import { dealingFields, signFields, verifyFields } from './signatures';
import { TAGS } from './tags';
import { type TranscriptInput, fingerprint, paperDeviceFingerprint, transcriptHash } from './transcript';

function fail(fault: CeremonyFault): never {
  throw new CeremonyCheckError(fault);
}

function expectedFingerprint(tenantId: string, participant: Readonly<CeremonyParticipant>): Promise<Bytes> {
  if (participant.sigPub === null) return paperDeviceFingerprint(tenantId, participant.encPub);
  return fingerprint(tenantId, participant.holderRef, participant.encPub, participant.sigPub);
}

async function fingerprints(facts: Readonly<CeremonyFacts>): Promise<Map<number, Bytes>> {
  const computed = new Map<number, Bytes>();
  for (const participant of facts.participants) {
    const value = await expectedFingerprint(facts.tenantId, participant);
    if (!equalBytes(value, participant.fingerprint)) fail('fingerprint_mismatch');
    computed.set(participant.holderIndex, value);
  }
  return computed;
}

function dealingSignatureFields(facts: Readonly<CeremonyFacts>, dealing: Readonly<PublishedDealing>) {
  return dealingFields({
    tenantId: facts.tenantId,
    ceremonyId: facts.ceremonyId,
    dealerIndex: dealing.dealerIndex,
    commitments: dealing.commitments,
    proof: dealing.proof,
  });
}

async function proofHolds(facts: Readonly<CeremonyFacts>, dealing: Readonly<PublishedDealing>): Promise<boolean> {
  if (dealing.commitments.length !== facts.k) return false;
  try {
    return await verifySchnorr(facts.tenantId, facts.ceremonyId, dealing.dealerIndex, dealing.commitments[0], dealing.proof);
  } catch {
    return false; // a commitment that is not a point
  }
}

/**
 * Each dealing proved and signed by its dealer (spec §9.2 step 4). A missing or
 * duplicated dealing changes the transcript, which `receive` compares next.
 */
async function verifyDealings(facts: Readonly<CeremonyFacts>): Promise<void> {
  const custodians = facts.participants.filter((participant) => participant.kind === 'custodian');
  for (const dealing of facts.dealings) {
    const dealer = custodians.find((custodian) => custodian.holderIndex === dealing.dealerIndex);
    if (dealer?.sigPub == null || !(await proofHolds(facts, dealing))) fail('proof_invalid');
    const signed = dealingSignatureFields(facts, dealing);
    if (!(await verifyFields(dealer.sigPub, dealing.signature, TAGS.dealingSig, signed))) fail('signature_invalid');
  }
}

async function openSubshare(
  facts: Readonly<CeremonyFacts>,
  receiver: Readonly<Receiver>,
  dealing: Readonly<PublishedDealing>,
  index: number,
  text: string | undefined
): Promise<bigint> {
  if (text === undefined) fail('subshare_invalid');
  let value: bigint;
  try {
    const context = contexts.subshare(facts.tenantId, facts.ceremonyId, dealing.dealerIndex, index);
    const sealed = parseSealed(text, TAGS.subshare);
    value = bytesToBigInt(await openWithPrivateKey(sealed, receiver.privateKey, receiver.publicKey, context));
  } catch {
    fail('subshare_invalid');
  }
  if (!verifySubshare(index, value, dealing.commitments)) fail('subshare_invalid');
  return value;
}

/** x_i = Σ_j f_j(i), every sub-share checked against its dealer's commitments. */
async function shareFor(
  facts: Readonly<CeremonyFacts>,
  receiver: Readonly<Receiver>,
  index: number,
  byDealer: ReadonlyMap<number, string>
): Promise<bigint> {
  let total = 0n;
  for (const dealing of facts.dealings) {
    total = mod(total + (await openSubshare(facts, receiver, dealing, index, byDealer.get(dealing.dealerIndex))));
  }
  return total;
}

/** The transcript of spec A.8, with X and every X_i derived from the commitments here. */
function transcriptOf(facts: Readonly<CeremonyFacts>): TranscriptInput {
  const dealings = [...facts.dealings].sort((left, right) => left.dealerIndex - right.dealerIndex);
  const lists = dealings.map((dealing) => dealing.commitments);
  const participants = [...facts.participants].sort((left, right) => left.holderIndex - right.holderIndex);
  return {
    tenantId: facts.tenantId,
    ceremonyId: facts.ceremonyId,
    k: facts.k,
    participants: participants.map((p) => ({ holderRef: p.holderRef, index: p.holderIndex, fingerprint: p.fingerprint })),
    dealings: dealings.map((d) => ({ dealerIndex: d.dealerIndex, commitments: d.commitments, proof: d.proof })),
    recoveryPublicKey: recoveryPublicKey(lists),
    holderShares: participants.map((p) => holderPublicShare(p.holderIndex, lists)),
    gatewayKeys: facts.gatewayKeys,
  };
}

/**
 * `kind` is not in the transcript; a signing key is, through the fingerprint. So a
 * holder with a signing key must have signed, and must be listed as a custodian.
 */
async function participantVouches(
  participant: Readonly<CeremonyParticipant>,
  signature: Bytes | undefined,
  transcript: Bytes
): Promise<boolean> {
  const custodian = participant.kind === 'custodian';
  if (participant.sigPub === null) return !custodian;
  if (!custodian || signature === undefined) return false;
  return verifyFields(participant.sigPub, signature, TAGS.transcript, [transcript]);
}

async function certifyTrust(
  facts: Readonly<CeremonyFacts>,
  expectedTranscript: Bytes,
  signatures: ReadonlyMap<number, Bytes>
): Promise<CertifiedTrust> {
  await fingerprints(facts);
  const input = transcriptOf(facts);
  const hash = await transcriptHash(input);
  if (!equalBytes(hash, expectedTranscript)) fail('transcript_mismatch');
  const vouched = await Promise.all(
    facts.participants.map((p) => participantVouches(p, signatures.get(p.holderIndex), hash))
  );
  if (vouched.includes(false)) fail('signature_invalid');
  const participants = [...facts.participants].sort((left, right) => left.holderIndex - right.holderIndex);
  return {
    recoveryKeyId: facts.ceremonyId,
    k: facts.k,
    transcriptHash: hash,
    recoveryPublicKey: input.recoveryPublicKey,
    participants,
    holderShares: new Map(participants.map((p, i) => [p.holderIndex, input.holderShares[i]])),
    gatewayKeys: new Map(facts.gatewayKeys.map((key) => [key.keyId, key.publicKey])),
  };
}

export function createWebCeremonyCrypto(): CeremonyCrypto {
  return {
    fingerprints,

    async deal(facts, dealerIndex, signingKey) {
      await fingerprints(facts);
      const coefficients = Array.from({ length: facts.k }, () => randomScalar());
      const commitments = commitmentsOf(coefficients);
      const proof = await schnorrProve(facts.tenantId, facts.ceremonyId, dealerIndex, coefficients[0], randomScalar());
      const published = { dealerIndex, commitments, proof, signature: new Uint8Array(0) };
      const signature = await signFields(signingKey, TAGS.dealingSig, dealingSignatureFields(facts, published));
      const subshares = new Map<number, string>();
      for (const participant of facts.participants) {
        const value = scalarToBytes(evaluatePolynomial(coefficients, participant.holderIndex));
        const context = contexts.subshare(facts.tenantId, facts.ceremonyId, dealerIndex, participant.holderIndex);
        subshares.set(participant.holderIndex, sealedToJson(await seal(TAGS.subshare, participant.encPub, value, context)));
      }
      return { commitments, proof, signature, subshares };
    },

    async receive(facts, receiver, subshares, expectedTranscript) {
      await fingerprints(facts);
      await verifyDealings(facts);
      const hash = await transcriptHash(transcriptOf(facts));
      if (!equalBytes(hash, expectedTranscript)) fail('transcript_mismatch');
      const shares = new Map<number, bigint>();
      for (const [index, byDealer] of subshares) {
        shares.set(index, await shareFor(facts, receiver, index, byDealer));
      }
      return { shares, transcriptHash: hash };
    },

    async confirm(facts, holder, share, hash, signingKey) {
      // The recovery key's ID is the ID of the ceremony that made it.
      const context = contexts.share(facts.tenantId, facts.ceremonyId, holder.holderIndex, holder.holderRef);
      const sealed = await seal(TAGS.share, holder.encPub, scalarToBytes(share), context);
      const transcriptSignature = await signFields(signingKey, TAGS.transcript, [hash]);
      return { transcriptSignature, encryptedShare: sealedToJson(sealed) };
    },

    async certify(facts, expectedTranscript, signatures) {
      return (await certifyTrust(facts, expectedTranscript, signatures)).gatewayKeys;
    },

    certifyTrust,

    async createPaperDevice(tenantId) {
      const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
      const publicKey = fromBuffer(await crypto.subtle.exportKey('raw', pair.publicKey));
      return { privateKey: pair.privateKey, publicKey, fingerprint: await paperDeviceFingerprint(tenantId, publicKey) };
    },
  };
}
