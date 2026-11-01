import { type Bytes, equalBytes, scalarToBytes } from './bytes';
import {
  type CeremonyFacts,
  type CeremonyFault,
  type CeremonyParticipant,
  CeremonyCheckError,
  type PublishedDealing,
} from './ceremony-crypto.port';
import { randomScalar } from './curve';
import { contexts, seal, sealedToJson } from './ecies';
import {
  type Proof,
  commitmentsOf,
  evaluatePolynomial,
  holderPublicShare,
  recoveryPublicKey,
  schnorrProve,
  verifySchnorr,
} from './proofs';
import { dealingFields, verifyFields } from './signatures';
import { TAGS } from './tags';
import { type TranscriptInput, fingerprint, paperDeviceFingerprint } from './transcript';

export function fail(fault: CeremonyFault): never {
  throw new CeremonyCheckError(fault);
}

function expectedFingerprint(
  tenantId: string,
  participant: Readonly<CeremonyParticipant>
): Promise<Bytes> {
  if (participant.sigPub === null) return paperDeviceFingerprint(tenantId, participant.encPub);
  return fingerprint(tenantId, participant.holderRef, participant.encPub, participant.sigPub);
}

export async function fingerprints(facts: Readonly<CeremonyFacts>): Promise<Map<number, Bytes>> {
  const computed = new Map<number, Bytes>();
  for (const participant of facts.participants) {
    const value = await expectedFingerprint(facts.tenantId, participant);
    if (!equalBytes(value, participant.fingerprint)) fail('fingerprint_mismatch');
    computed.set(participant.holderIndex, value);
  }
  return computed;
}

export function dealingSignatureFields(
  facts: Readonly<CeremonyFacts>,
  dealing: Readonly<PublishedDealing>
) {
  return dealingFields({
    tenantId: facts.tenantId,
    ceremonyId: facts.ceremonyId,
    dealerIndex: dealing.dealerIndex,
    commitments: dealing.commitments,
    proof: dealing.proof,
  });
}

export async function proofHolds(
  facts: Readonly<CeremonyFacts>,
  dealing: Readonly<PublishedDealing>
): Promise<boolean> {
  if (dealing.commitments.length !== facts.k) return false;
  try {
    return await verifySchnorr(
      facts.tenantId,
      facts.ceremonyId,
      dealing.dealerIndex,
      dealing.commitments[0],
      dealing.proof
    );
  } catch {
    return false; // a commitment that is not a point
  }
}

/** A dealer's polynomial made public: commitments, proof of a_0, one sealed sub-share per holder. */
export async function dealPolynomial(
  facts: Readonly<CeremonyFacts>,
  dealerIndex: number,
  coefficients: readonly bigint[]
): Promise<{ commitments: Bytes[]; proof: Proof; subshares: Map<number, string> }> {
  const commitments = commitmentsOf(coefficients);
  const proof = await schnorrProve(
    facts.tenantId,
    facts.ceremonyId,
    dealerIndex,
    coefficients[0],
    randomScalar()
  );
  const subshares = new Map<number, string>();
  for (const participant of facts.participants) {
    const value = scalarToBytes(evaluatePolynomial(coefficients, participant.holderIndex));
    const context = contexts.subshare(
      facts.tenantId,
      facts.ceremonyId,
      dealerIndex,
      participant.holderIndex
    );
    subshares.set(
      participant.holderIndex,
      sealedToJson(await seal(TAGS.subshare, participant.encPub, value, context))
    );
  }
  return { commitments, proof, subshares };
}

/**
 * Each dealing of a first ceremony proved and signed by its dealer (spec §9.2 step 4). A
 * missing or duplicated dealing changes the transcript, which `receive` compares next.
 */
export async function verifyFirstDealings(facts: Readonly<CeremonyFacts>): Promise<void> {
  const custodians = facts.participants.filter((participant) => participant.kind === 'custodian');
  for (const dealing of facts.dealings) {
    const dealer = custodians.find((custodian) => custodian.holderIndex === dealing.dealerIndex);
    if (dealer?.sigPub == null || !(await proofHolds(facts, dealing))) fail('proof_invalid');
    const signature = dealing.signature;
    if (signature === null) fail('signature_invalid');
    const signed = dealingSignatureFields(facts, dealing);
    if (!(await verifyFields(dealer.sigPub, signature, TAGS.dealingSig, signed)))
      fail('signature_invalid');
  }
}

/** The transcript of spec A.8, with X and every X_i derived from the commitments here. */
export function transcriptOf(facts: Readonly<CeremonyFacts>): TranscriptInput {
  const dealings = [...facts.dealings].sort((left, right) => left.dealerIndex - right.dealerIndex);
  const lists = dealings.map((dealing) => dealing.commitments);
  const participants = [...facts.participants].sort(
    (left, right) => left.holderIndex - right.holderIndex
  );
  return {
    tenantId: facts.tenantId,
    ceremonyId: facts.ceremonyId,
    k: facts.k,
    participants: participants.map((p) => ({
      holderRef: p.holderRef,
      index: p.holderIndex,
      fingerprint: p.fingerprint,
    })),
    dealings: dealings.map((d) => ({
      dealerIndex: d.dealerIndex,
      commitments: d.commitments,
      proof: d.proof,
    })),
    recoveryPublicKey: recoveryPublicKey(lists),
    holderShares: participants.map((p) => holderPublicShare(p.holderIndex, lists)),
    gatewayKeys: facts.gatewayKeys,
    previousTranscript: facts.resharing?.previousTranscript,
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

/** Every custodian signed exactly this transcript. */
export async function everyoneSigned(
  facts: Readonly<CeremonyFacts>,
  signatures: ReadonlyMap<number, Bytes>,
  transcript: Bytes
): Promise<void> {
  const vouched = await Promise.all(
    facts.participants.map((p) => participantVouches(p, signatures.get(p.holderIndex), transcript))
  );
  if (vouched.includes(false)) fail('signature_invalid');
}
