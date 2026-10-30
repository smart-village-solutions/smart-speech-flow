import { type Bytes, bytesToBigInt, equalBytes, fromBuffer, scalarToBytes } from './bytes';
import { certifyChain } from './chain-crypto';
import { dealPolynomial, dealingSignatureFields, fail, fingerprints, transcriptOf, verifyFirstDealings } from './ceremony-checks';
import {
  type CeremonyCrypto,
  type CeremonyFacts,
  type CeremonyParticipant,
  type Confirmation,
  type PublishedDealing,
  type Receiver,
} from './ceremony-crypto.port';
import { mod, randomScalar } from './curve';
import { contexts, openWithPrivateKey, parseSealed, seal, sealedToJson } from './ecies';
import { shareProofProve, verifySubshare } from './proofs';
import { certifiedResharing, dealShare, openShare, verifyResharingDealings } from './resharing-crypto';
import { signFields } from './signatures';
import { TAGS } from './tags';
import { paperDeviceFingerprint, transcriptHash } from './transcript';

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

/** A resharing's shares are sealed under the key's ID, as the certified chain names it (§9.7). */
function shareContext(facts: Readonly<CeremonyFacts>, holder: Readonly<CeremonyParticipant>) {
  const keyId = facts.resharing === undefined ? facts.ceremonyId : certifiedResharing(facts).previous.recoveryKeyId;
  return contexts.share(facts.tenantId, keyId, holder.holderIndex, holder.holderRef);
}

async function confirm(
  facts: Readonly<CeremonyFacts>,
  holder: Readonly<CeremonyParticipant>,
  share: bigint,
  hash: Bytes,
  signingKey: CryptoKey,
  receiver: Readonly<Receiver>
): Promise<Confirmation> {
  const context = shareContext(facts, holder);
  const sealed = await seal(TAGS.share, holder.encPub, scalarToBytes(share), context);
  const transcriptSignature = await signFields(signingKey, TAGS.transcript, [hash]);
  if (facts.resharing === undefined) {
    return { transcriptSignature, encryptedShare: sealedToJson(sealed), shareProof: null };
  }
  // Proven from what the stored blob gives back, so a blob that does not open fails here.
  const reopened = bytesToBigInt(await openWithPrivateKey(sealed, receiver.privateKey, receiver.publicKey, context));
  if (reopened !== share) fail('subshare_invalid');
  const shareProof = await shareProofProve(facts.tenantId, facts.ceremonyId, holder.holderIndex, reopened, randomScalar());
  return { transcriptSignature, encryptedShare: sealedToJson(sealed), shareProof };
}

export function createWebCeremonyCrypto(): CeremonyCrypto {
  return {
    fingerprints,

    async deal(facts, dealerIndex, signingKey) {
      await fingerprints(facts);
      const coefficients = Array.from({ length: facts.k }, () => randomScalar());
      const { commitments, proof, subshares } = await dealPolynomial(facts, dealerIndex, coefficients);
      const published = { dealerIndex, commitments, proof, signature: null };
      const signature = await signFields(signingKey, TAGS.dealingSig, dealingSignatureFields(facts, published));
      return { commitments, proof, signature, subshares };
    },

    dealShare,
    openShare,

    async receive(facts, receiver, subshares, expectedTranscript) {
      await fingerprints(facts);
      await (facts.resharing === undefined ? verifyFirstDealings(facts) : verifyResharingDealings(facts));
      const hash = await transcriptHash(transcriptOf(facts));
      if (!equalBytes(hash, expectedTranscript)) fail('transcript_mismatch');
      const shares = new Map<number, bigint>();
      for (const [index, byDealer] of subshares) {
        shares.set(index, await shareFor(facts, receiver, index, byDealer));
      }
      return { shares, transcriptHash: hash };
    },

    confirm,
    certifyChain,

    async createPaperDevice(tenantId) {
      const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
      const publicKey = fromBuffer(await crypto.subtle.exportKey('raw', pair.publicKey));
      return { privateKey: pair.privateKey, publicKey, fingerprint: await paperDeviceFingerprint(tenantId, publicKey) };
    },
  };
}
