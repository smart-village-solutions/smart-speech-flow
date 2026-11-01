import type { Bytes } from './bytes';
import type { Proof } from './proofs';

/** A holder as the gateway lists it; the browser recomputes the fingerprint from the keys. */
export interface CeremonyParticipant {
  holderIndex: number;
  holderRef: string;
  kind: 'custodian' | 'paper';
  displayName: string | null;
  encPub: Bytes;
  /** Null for a paper holder: the ceremony device has an encryption key only. */
  sigPub: Bytes | null;
  fingerprint: Bytes;
}

export interface PublishedDealing {
  dealerIndex: number;
  commitments: Bytes[];
  proof: Proof;
  /** Null only for a paper sheet dealing in a resharing: the device has no signing key. */
  signature: Bytes | null;
}

/** What a resharing adds to its facts (spec §9.7). */
export interface ResharingFacts {
  /** The key's ID, which is its first ceremony's; new shares are sealed under it. */
  recoveryKeyId: string;
  previousTranscript: Bytes;
  /** Old holder indices of the generation before, exactly its k. */
  dealers: number[];
  /** The generation before, certified by this browser; null until it is. */
  previous: CertifiedTrust | null;
}

/** Everything public about a ceremony that a browser checks before it deals, signs or prints. */
export interface CeremonyFacts {
  tenantId: string;
  ceremonyId: string;
  k: number;
  participants: CeremonyParticipant[];
  dealings: PublishedDealing[];
  gatewayKeys: { keyId: string; publicKey: Bytes }[];
  /** Set for a resharing; absent for a first ceremony. */
  resharing?: ResharingFacts;
}

/** One completed generation as the trust route serves it. */
export interface Generation {
  facts: CeremonyFacts;
  transcriptHash: Bytes;
  /** Holder index -> transcript signature, one per custodian. */
  signatures: Map<number, Bytes>;
}

/** The recovery key's generations, from the ceremony that made it to its current holders. */
export interface TrustChain {
  recoveryKeyId: string;
  /** The first transcript's hash: what every recovery wrap signs (A.6). */
  firstTranscriptHash: Bytes;
  /** The key's current holders, as it names them: the chain must end there. */
  holdersCeremonyId: string;
  holdersTranscriptHash: Bytes;
  generations: Generation[];
}

export interface NewDealing extends Omit<PublishedDealing, 'dealerIndex'> {
  /** Holder index -> the sub-share sealed for that holder. */
  subshares: Map<number, string>;
}

/** A decryption key that receives sub-shares: a custodian's personal key or the ceremony device. */
export interface Receiver {
  privateKey: CryptoKey;
  publicKey: Bytes;
}

export interface PaperDevice extends Receiver {
  fingerprint: Bytes;
}

export interface ReceivedShares {
  /** Holder index -> x_i. Raw scalars: held only until sealed or printed (spec §8.3). */
  shares: Map<number, bigint>;
  transcriptHash: Bytes;
}

export interface Confirmation {
  transcriptSignature: Bytes;
  encryptedShare: string;
  /** A resharing's custodian proves the share it sealed (spec §9.7); null otherwise. */
  shareProof: Proof | null;
}

/** Why a browser refuses to go on; each is also the abort reason it reports. */
export type CeremonyFault =
  | 'fingerprint_mismatch'
  | 'proof_invalid'
  | 'signature_invalid'
  | 'subshare_invalid'
  | 'transcript_mismatch'
  | 'contribution_invalid'
  | 'chain_invalid';

export class CeremonyCheckError extends Error {
  readonly fault: CeremonyFault;

  constructor(fault: CeremonyFault) {
    super(`ceremony check failed: ${fault}`);
    this.name = 'CeremonyCheckError';
    this.fault = fault;
  }
}

/** A typed-in or stored share that is not the one the transcript lists: a typo, not a fault. */
export class ShareMismatchError extends Error {
  constructor() {
    super('the share does not match its public share');
    this.name = 'ShareMismatchError';
  }
}

/** x_i for `index`. Sub-shares the gateway left out fail like bad ones, never as a zero share. */
export function heldShare(received: Readonly<ReceivedShares>, index: number): bigint {
  const share = received.shares.get(index);
  if (share === undefined) throw new CeremonyCheckError('subshare_invalid');
  return share;
}

/** What a certified transcript vouches for: the browser derives X and every X_i itself. */
export interface CertifiedTrust {
  /** The recovery key's ID, which is its first ceremony's. */
  recoveryKeyId: string;
  /** The current holders' threshold. */
  k: number;
  /** The first transcript's hash, which recovery wraps sign. */
  transcriptHash: Bytes;
  /** The current generation's ceremony and transcript. */
  holdersCeremonyId: string;
  holdersTranscriptHash: Bytes;
  recoveryPublicKey: Bytes;
  participants: CeremonyParticipant[];
  /** Holder index -> X_i, of the current holders. */
  holderShares: Map<number, Bytes>;
  /** Every generation's gateway keys together. */
  gatewayKeys: Map<string, Bytes>;
}

/** The browser's part of the recovery-key ceremony (spec §9.2). Features reach it through this port only. */
export interface CeremonyCrypto {
  /** Rejects with CeremonyCheckError('fingerprint_mismatch') if a listed fingerprint does not match its keys. */
  fingerprints(facts: Readonly<CeremonyFacts>): Promise<Map<number, Bytes>>;
  deal(facts: Readonly<CeremonyFacts>, dealerIndex: number, signingKey: CryptoKey): Promise<NewDealing>;
  /**
   * A resharing dealer's dealing of λ_i·x_i (spec §9.7). `signingKey` is null for a paper sheet.
   * Rejects with ShareMismatchError when x_i is not the share the previous generation lists.
   */
  dealShare(
    facts: Readonly<CeremonyFacts>,
    dealerIndex: number,
    share: bigint,
    signingKey: CryptoKey | null
  ): Promise<NewDealing>;
  /** A custodian dealer's own share of the previous generation, checked against its X_i. */
  openShare(
    facts: Readonly<CeremonyFacts>,
    dealer: Readonly<CeremonyParticipant>,
    encryptedShare: string,
    receiver: Readonly<Receiver>
  ): Promise<bigint>;
  /**
   * Verifies every dealing, opens and checks the sub-shares for `receiver`, and sums them.
   * Rejects with CeremonyCheckError on any fault, including a transcript that differs from `expectedTranscript`.
   */
  receive(
    facts: Readonly<CeremonyFacts>,
    receiver: Readonly<Receiver>,
    subshares: ReadonlyMap<number, ReadonlyMap<number, string>>,
    expectedTranscript: Bytes
  ): Promise<ReceivedShares>;
  /** For a resharing, `receiver` reopens the sealed share, and the proof is made from that. */
  confirm(
    facts: Readonly<CeremonyFacts>,
    holder: Readonly<CeremonyParticipant>,
    share: bigint,
    transcriptHash: Bytes,
    signingKey: CryptoKey,
    receiver: Readonly<Receiver>
  ): Promise<Confirmation>;
  createPaperDevice(tenantId: string): Promise<PaperDevice>;
  /**
   * The current holders a chain of generations vouches for (spec §9.7, §10.6): the first
   * ceremony as signed, then every resharing linked to it with X unchanged. Rejects with
   * CeremonyCheckError otherwise.
   */
  certifyChain(chain: Readonly<TrustChain>): Promise<CertifiedTrust>;
}

/** The ceremony device's key, in memory for as long as this tab lives. */
export interface PaperDeviceHolder {
  current(): PaperDevice | null;
  hold(device: PaperDevice): void;
  clear(): void;
}
