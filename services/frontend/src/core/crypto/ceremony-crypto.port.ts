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
  signature: Bytes;
}

/** Everything public about a ceremony that a browser checks before it deals, signs or prints. */
export interface CeremonyFacts {
  tenantId: string;
  ceremonyId: string;
  k: number;
  participants: CeremonyParticipant[];
  dealings: PublishedDealing[];
  gatewayKeys: { keyId: string; publicKey: Bytes }[];
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
}

/** Why a browser refuses to go on; each is also the abort reason it reports. */
export type CeremonyFault =
  | 'fingerprint_mismatch'
  | 'proof_invalid'
  | 'signature_invalid'
  | 'subshare_invalid'
  | 'transcript_mismatch';

export class CeremonyCheckError extends Error {
  readonly fault: CeremonyFault;

  constructor(fault: CeremonyFault) {
    super(`ceremony check failed: ${fault}`);
    this.name = 'CeremonyCheckError';
    this.fault = fault;
  }
}

/** The browser's part of the recovery-key ceremony (spec §9.2). Features reach it through this port only. */
export interface CeremonyCrypto {
  /** Rejects with CeremonyCheckError('fingerprint_mismatch') if a listed fingerprint does not match its keys. */
  fingerprints(facts: Readonly<CeremonyFacts>): Promise<Map<number, Bytes>>;
  deal(facts: Readonly<CeremonyFacts>, dealerIndex: number, signingKey: CryptoKey): Promise<NewDealing>;
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
  confirm(
    facts: Readonly<CeremonyFacts>,
    holder: Readonly<CeremonyParticipant>,
    share: bigint,
    transcriptHash: Bytes,
    signingKey: CryptoKey
  ): Promise<Confirmation>;
  createPaperDevice(tenantId: string): Promise<PaperDevice>;
}

/** The ceremony device's key, in memory for as long as this tab lives. */
export interface PaperDeviceHolder {
  current(): PaperDevice | null;
  hold(device: PaperDevice): void;
  clear(): void;
}
