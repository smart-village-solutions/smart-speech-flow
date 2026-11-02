import type { Bytes } from '@/core/crypto/bytes';
import type { TrustChain } from '@/core/crypto/ceremony-crypto.port';
import type { SignedEntry } from '@/core/crypto/chain';

/** Derived from the records, never stored (spec §10.5, §10.7). */
export interface VerificationSummary {
  status: 'not_verified' | 'in_review' | 'decided';
  approved: number;
  notApproved: number;
}

export type VerificationStatus =
  | 'awaiting'
  | 'in_review'
  | 'approved'
  | 'not_approved'
  | 'declined'
  | 'withdrawn';

export interface SealedNoteFacts {
  entryId: string;
  keyId: string;
  ciphertext: Bytes;
}

/** What only a decided record carries (spec §10.7): its content and what proves it. */
export interface DecidedFacts {
  outcome: 'approved' | 'not_approved';
  overallNote: Bytes | null;
  notes: SealedNoteFacts[];
  signature: Bytes;
  reviewerKey: { keyVersion: number; encPub: Bytes; sigPub: Bytes } | null;
  tsaToken: Bytes | null;
}

export interface VerificationRecord {
  verificationId: string;
  status: VerificationStatus;
  requestedBy: string;
  requestedAt: string;
  reviewerSub: string;
  reviewerName: string | null;
  reviewerKeyVersion: number;
  reviewerFingerprint: Bytes;
  startedAt: string | null;
  reviewedHeadSeq: number | null;
  reviewedHead: Bytes | null;
  permissionSnapshot: string[] | null;
  decidedAt: string | null;
  closedAt: string | null;
  closeReason: 'declined' | 'key_retired' | 'permission_revoked' | null;
  decided: DecidedFacts | null;
}

/** A reviewer the gateway found eligible; the browser filters by language (spec §10.7). */
export interface ReviewerCandidate {
  sub: string;
  displayName: string;
  languages: string[];
  sworn: boolean;
  keyVersion: number;
  fingerprint: Bytes;
  fingerprintDisplay: string;
  encPub: Bytes;
  sigPub: Bytes;
}

export interface AssignPost {
  keyVersion: number;
  reviewerSub: string;
  reviewerKeyVersion: number;
  wraps: { keyId: string; blob: string; signature: Bytes }[];
}

/** A row of the caller's archive: clear metadata only (spec §10.6, §9.5). */
export interface OwnConversation {
  conversationId: string;
  employeeSub: string;
  /** The directory's name for a recovered row's employee; null for one's own or when unknown. */
  employeeName: string | null;
  /** Someone else's conversation, opened through a completed recovery request. */
  recovered: boolean;
  startedAt: string;
  endedAt: string;
  retentionUntil: string;
  legalHold: boolean;
  incomplete: boolean;
  messages: number;
  amendments: number;
  verification: VerificationSummary;
}

export interface ConversationFacts {
  conversationId: string;
  employeeSub: string;
  legalBasis: 'consent' | 'statutory';
  startedAt: string;
  endedAt: string;
  retentionUntil: string;
  legalHold: boolean;
  incomplete: boolean;
  verification: VerificationSummary;
}

export interface PauseFacts {
  at: string;
  reason: string;
  resumedAt: string | null;
}

export interface WindowFacts {
  windowId: string;
  openedAt: string;
  closedAt: string | null;
  closeReason: string | null;
  pauses: PauseFacts[];
}

export interface ArchivedEntry extends SignedEntry {
  createdAt: string;
  /** Object types the store has confirmed; the rest are still in the spool. */
  storedTypes: string[];
}

export interface StampFacts {
  headSeq: number;
  headHash: Bytes;
  token: Bytes | null;
}

export interface KeyFacts {
  keyId: string;
  epoch: number;
  recoveryWrapped: boolean;
  /** The caller's wrap of this key, if any. */
  wrap: { blob: string; creatorRef: string; creatorSignature: Bytes } | null;
}

export interface OpenedConversation {
  conversation: ConversationFacts;
  windows: WindowFacts[];
  entries: ArchivedEntry[];
  stamps: StampFacts[];
  keys: KeyFacts[];
  verifications: VerificationRecord[];
}

/** The recovery key's generations: what certifies the gateway's signing keys (spec A.6, §9.7). */
export type ArchiveTrust = TrustChain;
