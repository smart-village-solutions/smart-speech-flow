import { type Bytes, bytesToBigInt, equalBytes } from './bytes';
import { dealPolynomial, fail, fingerprints, proofHolds } from './ceremony-checks';
import {
  type CeremonyFacts,
  type CeremonyParticipant,
  type CertifiedTrust,
  type NewDealing,
  type PublishedDealing,
  type Receiver,
  type ResharingFacts,
  ShareMismatchError,
} from './ceremony-crypto.port';
import { mod, publicPoint, randomScalar } from './curve';
import { contexts, openWithPrivateKey, parseSealed } from './ecies';
import { contribution, lagrangeAtZero, recoveryPublicKey } from './proofs';
import { participantsDigest, reshareDealingFields, signFields, verifyFields } from './signatures';
import { TAGS } from './tags';

/** The resharing's facts with its previous generation certified, or a chain fault. */
/**
 * The resharing with the generation it replaces, certified here. It must name that very
 * generation and key: served values that differ would seal the new shares where no
 * approval can open them, after the old ones are gone (spec §9.7).
 */
export function certifiedResharing(
  facts: Readonly<CeremonyFacts>
): ResharingFacts & { previous: CertifiedTrust } {
  const resharing = facts.resharing;
  const previous = resharing?.previous;
  if (
    resharing === undefined ||
    previous == null ||
    resharing.recoveryKeyId !== previous.recoveryKeyId ||
    !equalBytes(resharing.previousTranscript, previous.holdersTranscriptHash)
  ) {
    fail('chain_invalid');
  }
  return { ...resharing, previous };
}

function holdersDigest(facts: Readonly<CeremonyFacts>): Promise<Bytes> {
  return participantsDigest(
    facts.participants.map((p) => ({
      index: p.holderIndex,
      holderRef: p.holderRef,
      fingerprint: p.fingerprint,
    }))
  );
}

async function signedFields(facts: Readonly<CeremonyFacts>, dealing: Readonly<PublishedDealing>) {
  const resharing = certifiedResharing(facts);
  return reshareDealingFields({
    tenantId: facts.tenantId,
    ceremonyId: facts.ceremonyId,
    dealerIndex: dealing.dealerIndex,
    commitments: dealing.commitments,
    proof: dealing.proof,
    previousTranscript: resharing.previousTranscript,
    participantsDigest: await holdersDigest(facts),
  });
}

/** A custodian dealer signed this dealing over the new holder set; a paper sheet signed nothing. */
async function dealerConsented(
  facts: Readonly<CeremonyFacts>,
  dealer: Readonly<CeremonyParticipant>,
  dealing: Readonly<PublishedDealing>
): Promise<boolean> {
  if (dealer.sigPub === null) return dealing.signature === null;
  if (dealing.signature === null) return false;
  return verifyFields(
    dealer.sigPub,
    dealing.signature,
    TAGS.reshareDealingSig,
    await signedFields(facts, dealing)
  );
}

function dealersAreHolders(
  resharing: Readonly<ResharingFacts>,
  previous: Readonly<CertifiedTrust>
): boolean {
  const distinct = new Set(resharing.dealers);
  return (
    distinct.size === resharing.dealers.length &&
    distinct.size === previous.k &&
    resharing.dealers.every((index) => previous.holderShares.has(index))
  );
}

/**
 * Spec §9.7: exactly k old holders deal, each C_i0 is λ_i·X_i of the generation before,
 * each custodian dealer consented to the new set, and Σ C_i0 is the same X.
 */
export async function verifyResharingDealings(facts: Readonly<CeremonyFacts>): Promise<void> {
  const resharing = certifiedResharing(facts);
  const previous = resharing.previous;
  const dealt = facts.dealings
    .map((dealing) => dealing.dealerIndex)
    .sort((left, right) => left - right);
  const listed = [...resharing.dealers].sort((left, right) => left - right);
  if (!dealersAreHolders(resharing, previous) || dealt.join() !== listed.join())
    fail('chain_invalid');
  for (const dealing of facts.dealings) {
    const dealer = previous.participants.find((p) => p.holderIndex === dealing.dealerIndex);
    const publicShare = previous.holderShares.get(dealing.dealerIndex);
    if (dealer === undefined || publicShare === undefined) fail('chain_invalid');
    if (!(await proofHolds(facts, dealing))) fail('proof_invalid');
    if (
      !equalBytes(
        dealing.commitments[0],
        contribution(dealing.dealerIndex, resharing.dealers, publicShare)
      )
    ) {
      fail('contribution_invalid');
    }
    if (!(await dealerConsented(facts, dealer, dealing))) fail('signature_invalid');
  }
  if (
    !equalBytes(
      recoveryPublicKey(facts.dealings.map((d) => d.commitments)),
      previous.recoveryPublicKey
    )
  ) {
    fail('contribution_invalid');
  }
}

/** g_i(0) = λ_i·x_i over the dealers, sub-shared to the new holders (spec §9.7). */
export async function dealShare(
  facts: Readonly<CeremonyFacts>,
  dealerIndex: number,
  share: bigint,
  signingKey: CryptoKey | null
): Promise<NewDealing> {
  const resharing = certifiedResharing(facts);
  const publicShare = resharing.previous.holderShares.get(dealerIndex);
  if (publicShare === undefined || !equalBytes(publicPoint(share), publicShare))
    throw new ShareMismatchError();
  await fingerprints(facts);
  const weight = lagrangeAtZero(dealerIndex, resharing.dealers);
  const coefficients = [
    mod(weight * share),
    ...Array.from({ length: facts.k - 1 }, () => randomScalar()),
  ];
  const { commitments, proof, subshares } = await dealPolynomial(facts, dealerIndex, coefficients);
  const published = { dealerIndex, commitments, proof, signature: null };
  const signature =
    signingKey === null
      ? null
      : await signFields(signingKey, TAGS.reshareDealingSig, await signedFields(facts, published));
  return { commitments, proof, signature, subshares };
}

/** The dealer's share as the generation before sealed it, under the key's ID. */
export async function openShare(
  facts: Readonly<CeremonyFacts>,
  dealer: Readonly<CeremonyParticipant>,
  encryptedShare: string,
  receiver: Readonly<Receiver>
): Promise<bigint> {
  const resharing = certifiedResharing(facts);
  const context = contexts.share(
    facts.tenantId,
    resharing.recoveryKeyId,
    dealer.holderIndex,
    dealer.holderRef
  );
  const sealed = parseSealed(encryptedShare, TAGS.share);
  const share = bytesToBigInt(
    await openWithPrivateKey(sealed, receiver.privateKey, receiver.publicKey, context)
  );
  const publicShare = resharing.previous.holderShares.get(dealer.holderIndex);
  if (publicShare === undefined || !equalBytes(publicPoint(share), publicShare))
    throw new ShareMismatchError();
  return share;
}
