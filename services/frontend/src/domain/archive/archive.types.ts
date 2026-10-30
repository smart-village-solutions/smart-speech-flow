import type { Bytes } from '@/core/crypto/bytes';
import type { TrustChain } from '@/core/crypto/ceremony-crypto.port';
import type { SignedEntry } from '@/core/crypto/chain';

/** Derived until verification records exist (#619, spec §10.5). */
export type VerificationSummary = 'not_verified';

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
}

/** The recovery key's generations: what certifies the gateway's signing keys (spec A.6, §9.7). */
export type ArchiveTrust = TrustChain;
