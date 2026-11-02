import type { Bytes } from '@/core/crypto/bytes';
import type {
  OpenedConversation,
  SealedNoteFacts,
  VerificationRecord,
  VerificationStatus,
} from '@/domain/archive/archive.types';

export interface InboxRow {
  verificationId: string;
  status: VerificationStatus;
  requestedAt: string;
  requestedBy: string;
  startedAt: string;
  endedAt: string | null;
  messages: number;
  /** False once the conversation is shredded or past its date: the row opens nothing. */
  openable: boolean;
  /** The directory's name for the requester; null when Studio has none or cannot answer. */
  requestedByName: string | null;
}

export interface RequesterKey {
  sub: string;
  keyVersion: number;
  fingerprint: Bytes;
  encPub: Bytes;
  sigPub: Bytes;
}

export interface ReviewDraft {
  overall: Bytes | null;
  notes: SealedNoteFacts[];
}

export interface ReviewOpened {
  opened: OpenedConversation;
  record: VerificationRecord;
  draft: ReviewDraft;
  requester: RequesterKey | null;
  requesterName: string | null;
}

export interface DecisionPost extends ReviewDraft {
  outcome: 'approved' | 'not_approved';
  signature: Bytes;
}
