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

/** x_i for `index`. Sub-shares the gateway left out fail like bad ones, never as a zero share. */
export function heldShare(received: Readonly<ReceivedShares>, index: number): bigint {
  const share = received.shares.get(index);
  if (share === undefined) throw new CeremonyCheckError('subshare_invalid');
  return share;
}

/** What a certified transcript vouches for: the browser derives X and every X_i itself. */
export interface CertifiedTrust {
  /** The recovery key's ID, which is its ceremony's. */
  recoveryKeyId: string;
  k: number;
  transcriptHash: Bytes;
  recoveryPublicKey: Bytes;
  participants: CeremonyParticipant[];
  /** Holder index -> X_i. */
  holderShares: Map<number, Bytes>;
  gatewayKeys: Map<string, Bytes>;
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
  /**
   * The gateway keys a closed ceremony vouches for (spec A.6, §10.6): every
   * fingerprint matches its keys, the transcript is `transcriptHash`, and every
   * custodian signed it. Rejects with CeremonyCheckError otherwise.
   */
  certify(
    facts: Readonly<CeremonyFacts>,
    transcriptHash: Bytes,
    signatures: ReadonlyMap<number, Bytes>
  ): Promise<Map<string, Bytes>>;
  /** The same checks as `certify`, returning everything a recovery needs (spec §9.5). */
  certifyTrust(
    facts: Readonly<CeremonyFacts>,
    transcriptHash: Bytes,
    signatures: ReadonlyMap<number, Bytes>
  ): Promise<CertifiedTrust>;
}

/** The ceremony device's key, in memory for as long as this tab lives. */
export interface PaperDeviceHolder {
  current(): PaperDevice | null;
  hold(device: PaperDevice): void;
  clear(): void;
}
