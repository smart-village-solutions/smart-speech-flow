import { equalBytes } from './bytes';
import { everyoneSigned, fail, fingerprints, transcriptOf } from './ceremony-checks';
import type { CeremonyFacts, CertifiedTrust, Generation, TrustChain } from './ceremony-crypto.port';
import { verifyResharingDealings } from './resharing-crypto';
import { transcriptHash } from './transcript';

/** One generation: its fingerprints, its dealings, its transcript and every custodian's signature. */
async function certifyGeneration(
  generation: Readonly<Generation>,
  facts: Readonly<CeremonyFacts>,
  previous: Readonly<CertifiedTrust> | null
): Promise<CertifiedTrust> {
  await fingerprints(facts);
  if (previous !== null) await verifyResharingDealings(facts);
  const input = transcriptOf(facts);
  const hash = await transcriptHash(input);
  if (!equalBytes(hash, generation.transcriptHash)) fail('transcript_mismatch');
  await everyoneSigned(facts, generation.signatures, hash);
  const participants = [...facts.participants].sort(
    (left, right) => left.holderIndex - right.holderIndex
  );
  return {
    recoveryKeyId: previous?.recoveryKeyId ?? facts.ceremonyId,
    k: facts.k,
    transcriptHash: previous?.transcriptHash ?? hash,
    holdersCeremonyId: facts.ceremonyId,
    holdersTranscriptHash: hash,
    recoveryPublicKey: input.recoveryPublicKey,
    participants,
    holderShares: new Map(participants.map((p, i) => [p.holderIndex, input.holderShares[i]])),
    gatewayKeys: new Map([
      ...(previous?.gatewayKeys ?? []),
      ...facts.gatewayKeys.map((key) => [key.keyId, key.publicKey] as const),
    ]),
  };
}

/**
 * A later generation's facts with the one before attached; its dealings then require that
 * it is a resharing naming that generation and key (resharing-crypto `certifiedResharing`).
 */
function linked(
  generation: Readonly<Generation>,
  previous: Readonly<CertifiedTrust>
): CeremonyFacts {
  const resharing = generation.facts.resharing;
  return { ...generation.facts, resharing: resharing && { ...resharing, previous } };
}

/**
 * The key's current holders, from the ceremony that made it through every resharing
 * (spec §9.7, §10.6). Each link must name the one before and keep X.
 */
export async function certifyChain(chain: Readonly<TrustChain>): Promise<CertifiedTrust> {
  const [first, ...reshared] = chain.generations;
  if (
    first === undefined ||
    first.facts.resharing !== undefined ||
    first.facts.ceremonyId !== chain.recoveryKeyId ||
    !equalBytes(first.transcriptHash, chain.firstTranscriptHash)
  ) {
    fail('chain_invalid');
  }
  let trust = await certifyGeneration(first, first.facts, null);
  for (const generation of reshared) {
    trust = await certifyGeneration(generation, linked(generation, trust), trust);
  }
  // A chain cut short would certify holders the key has since replaced.
  if (
    trust.holdersCeremonyId !== chain.holdersCeremonyId ||
    !equalBytes(trust.holdersTranscriptHash, chain.holdersTranscriptHash)
  ) {
    fail('chain_invalid');
  }
  return trust;
}
