import type { PublicKeys, UnlockedKeys } from './archive-crypto.port';
import type { Bytes } from './bytes';
import type { CertifiedTrust } from './ceremony-crypto.port';
import type { RequestKind, ScopePair } from './signatures';

export type { RequestKind, ScopePair } from './signatures';

export interface RequestToSign {
  tenantId: string;
  requestId: string;
  kind: RequestKind;
  recoveryKeyId: string;
  requesterSub: string;
  reason: string;
  scope: readonly ScopePair[];
}

/** A recovery wrap as an approver sees it: R and its signature, never its ciphertext. */
export interface RecoveryWrapRef extends ScopePair {
  ephemeral: Bytes;
  signerKeyId: string;
  signature: Bytes;
}

export interface ApprovalFacts {
  tenantId: string;
  requestId: string;
  /** As served; the request signature covers it, so a relabelled request fails. */
  kind: RequestKind;
  recoveryKeyId: string;
  requesterSub: string;
  requesterKeys: PublicKeys;
  reason: string;
  requestSignature: Bytes;
  signedScope: readonly ScopePair[];
  keys: readonly RecoveryWrapRef[];
  holderIndex: number;
  attempt: number;
  encryptedShare: string;
  /** The fingerprint the custodian compared and ticked; partials are sealed to its keys only. */
  confirmedFingerprint: Bytes;
}

export interface ApprovalResult {
  /** Key ID -> sealed partial, the JSON text the signature covers. */
  partials: Map<string, string>;
  signature: Bytes;
}

export interface ServedRecoveryWrap extends ScopePair {
  blob: string;
  signerKeyId: string;
  signature: Bytes;
}

export interface ServedApproval {
  holderIndex: number;
  attempt: number;
  signedPartials: { keyId: string; hash: Bytes }[];
  signature: Bytes;
  partials: Map<string, string>;
}

export interface CombineFacts {
  tenantId: string;
  requestId: string;
  requesterSub: string;
  wraps: readonly ServedRecoveryWrap[];
  approvals: readonly ServedApproval[];
}

export type RejectionFault = 'partial_unreadable' | 'proof_invalid';
export type RecoveryIntegrityStage =
  | 'wrap_signature'
  | 'approval_signature'
  | 'partial_hash'
  | 'wrap_damaged';

export interface Rejection {
  holderIndex: number;
  attempt: number;
  fault: RejectionFault;
}

export interface NewRecoveredWrap extends ScopePair {
  blob: string;
  signature: Bytes;
}

/** A key whose recovery wrap cannot be used: it is reported, then left out of the store. */
export interface UnrecoverableKey {
  keyId: string;
  stage: 'wrap_signature' | 'wrap_damaged';
}

/** Called after each chunk, so a run over thousands of keys can show how far it got. */
export type OnProgress = (done: number, total: number) => void;

export interface CombineResult {
  /** Null until k valid approvals hold; then one wrap per key that opened. */
  wraps: NewRecoveredWrap[] | null;
  unrecoverable: UnrecoverableKey[];
  /** The custodians whose partials failed: theirs to answer for. */
  rejections: Rejection[];
  /** Faults of the served data, which name no custodian. */
  integrity: RecoveryIntegrityStage[];
}

export type RecoveryFault =
  | 'fingerprint_changed'
  | 'self_approval'
  | 'not_listed'
  | 'request_signature'
  | 'out_of_scope'
  | 'wrap_signature'
  | 'share_mismatch'
  | 'step_up'
  | 'custodians_changed';

export class RecoveryCheckError extends Error {
  readonly fault: RecoveryFault;

  constructor(fault: RecoveryFault) {
    super(`recovery check failed: ${fault}`);
    this.name = 'RecoveryCheckError';
    this.fault = fault;
  }
}

/** The browser's part of exceptional access (spec §9.5). Features reach it through this port only. */
export interface RecoveryCrypto {
  /** A.9 over the served keys: what the custodian reads out and compares by phone. */
  fingerprintOf(tenantId: string, sub: string, keys: Readonly<PublicKeys>): Promise<Bytes>;
  signRequest(request: Readonly<RequestToSign>, signingKey: CryptoKey): Promise<Bytes>;
  /** Rejects with RecoveryCheckError before anything is computed from the share. */
  approve(
    facts: Readonly<ApprovalFacts>,
    trust: Readonly<CertifiedTrust>,
    keys: Readonly<UnlockedKeys>,
    callerSub: string,
    onProgress?: OnProgress
  ): Promise<ApprovalResult>;
  combine(
    facts: Readonly<CombineFacts>,
    trust: Readonly<CertifiedTrust>,
    keys: Readonly<UnlockedKeys>,
    onProgress?: OnProgress
  ): Promise<CombineResult>;
}
