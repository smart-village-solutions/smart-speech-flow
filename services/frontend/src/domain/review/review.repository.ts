import type { AxiosInstance } from 'axios';
import { toBase64Url } from '@/core/crypto/bytes';
import type { SealedNoteFacts, VerificationRecord } from '@/domain/archive/archive.types';
import { toInbox, toReviewOpened, toStarted } from './review.mapper';
import type { DecisionPost, InboxRow, ReviewDraft, ReviewOpened } from './review.types';

const BASE = '/api/admin/recording/reviews';

export interface ReviewRepository {
  inbox(): Promise<InboxRow[]>;
  open(verificationId: string): Promise<ReviewOpened>;
  /** Also how a reviewer refreshes the permission snapshot after PERMISSIONS_CHANGED. */
  start(verificationId: string, expectedHeadSeq: number): Promise<VerificationRecord>;
  saveDraft(verificationId: string, draft: Readonly<ReviewDraft>): Promise<void>;
  decline(verificationId: string): Promise<void>;
  decide(verificationId: string, decision: Readonly<DecisionPost>): Promise<VerificationRecord>;
}

function notesBody(notes: readonly SealedNoteFacts[]) {
  return notes.map((n) => ({
    entry_id: n.entryId,
    key_id: n.keyId,
    ciphertext: toBase64Url(n.ciphertext),
  }));
}

function draftBody(draft: Readonly<ReviewDraft>) {
  return {
    overall: draft.overall === null ? null : toBase64Url(draft.overall),
    notes: notesBody(draft.notes),
  };
}

export function createReviewRepository(http: AxiosInstance): ReviewRepository {
  return {
    async inbox() {
      return toInbox((await http.get<unknown>(BASE)).data);
    },

    async open(verificationId) {
      return toReviewOpened((await http.get<unknown>(`${BASE}/${verificationId}`)).data);
    },

    async start(verificationId, expectedHeadSeq) {
      const response = await http.post<unknown>(`${BASE}/${verificationId}/start`, {
        expected_head_seq: expectedHeadSeq,
      });
      return toStarted(response.data);
    },

    async saveDraft(verificationId, draft) {
      await http.put(`${BASE}/${verificationId}/draft`, draftBody(draft));
    },

    async decline(verificationId) {
      await http.post(`${BASE}/${verificationId}/decline`);
    },

    async decide(verificationId, decision) {
      const response = await http.post<unknown>(`${BASE}/${verificationId}/decision`, {
        ...draftBody(decision),
        outcome: decision.outcome,
        signature: toBase64Url(decision.signature),
      });
      return toStarted(response.data);
    },
  };
}
