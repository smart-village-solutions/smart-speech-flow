import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { SignedEntry } from '@/core/crypto/chain';

/** Derived until verification records exist (#619, spec §10.5). */
export type VerificationSummary = 'not_verified';

/** A row of the employee's own archive: clear metadata only (spec §10.6). */
export interface OwnConversation {
  conversationId: string;
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
}

/** The active recovery key's ceremony: what certifies the gateway's signing keys (spec A.6). */
export interface ArchiveTrust {
  recoveryKeyId: string;
  transcriptHash: Bytes;
  facts: CeremonyFacts;
  /** Holder index -> transcript signature, one per custodian. */
  signatures: Map<number, Bytes>;
}
