import type { Bytes } from '@/core/crypto/bytes';
import type {
  RecoveryWrapRef,
  RequestKind,
  ScopePair,
  ServedApproval,
  ServedRecoveryWrap,
} from '@/core/crypto/recovery-crypto.port';

export type RequestStatus = 'open' | 'completed' | 'cancelled' | 'expired' | 'scope_gone';

/** Anyone whose conversations are recorded, leavers included; the name is the directory's. */
export interface RecoveryEmployee {
  sub: string;
  displayName: string | null;
}

/** A conversation a request may list: clear metadata and its key IDs, for the signature. */
export interface RecoveryCandidate {
  conversationId: string;
  startedAt: string;
  endedAt: string;
  retentionUntil: string;
  legalHold: boolean;
  incomplete: boolean;
  keyIds: string[];
}

export interface RequestSummary {
  requestId: string;
  kind: RequestKind;
  requesterSub: string;
  status: RequestStatus;
  reason: string;
  createdAt: string;
  expiresAt: string;
  conversations: number;
}

export interface RecoveryDecision {
  holderIndex: number;
  attempt: number;
  custodianSub: string;
  custodianName: string | null;
  decision: 'approved' | 'declined';
  reason: string | null;
  decidedAt: string;
  rejected: boolean;
}

export interface RequestProgress extends RequestSummary {
  k: number;
  decisions: RecoveryDecision[];
  /** The remaining scope. */
  scope: ScopePair[];
}

export interface ApprovalKey extends RecoveryWrapRef {
  employeeSub: string;
  employeeName: string | null;
  startedAt: string;
  endedAt: string;
}

/** What a custodian approves: never a recovery wrap's ciphertext (spec §9.5). */
export interface ApprovalDetail {
  requestId: string;
  kind: RequestKind;
  recoveryKeyId: string;
  requesterSub: string;
  requesterName: string | null;
  requesterEncPub: Bytes;
  requesterSigPub: Bytes;
  reason: string;
  createdAt: string;
  expiresAt: string;
  requestSignature: Bytes;
  signedScope: ScopePair[];
  keys: ApprovalKey[];
  holderIndex: number;
  attempt: number;
  encryptedShare: string;
}

export interface ServedPartials {
  wraps: ServedRecoveryWrap[];
  approvals: ServedApproval[];
  /** The holders the request was filed under; it must be the generation this browser certified. */
  holdersCeremonyId: string;
}

/** The caller's next key-recovery batch, and what lies beyond it (spec §9.6). */
export interface OwnCandidates {
  conversations: RecoveryCandidate[];
  remaining: { conversations: number; keys: number };
}

export interface ApprovalsList {
  requests: RequestSummary[];
  /** The caller's share belongs to an earlier key: nothing is theirs to decide until resharing. */
  shareStale: boolean;
}
