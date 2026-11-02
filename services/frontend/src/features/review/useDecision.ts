import { useMutation } from '@tanstack/react-query';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { notesDigest } from '@/core/crypto/verification';
import { AppError } from '@/core/http/AppError';
import type { VerificationRecord } from '@/domain/archive/archive.types';
import type { ReviewDraft } from '@/domain/review/review.types';
import type { ReviewState } from './openReview';

type Ready = Extract<ReviewState, { status: 'ready' }>;
type Outcome = 'approved' | 'not_approved';

const KNOWN = new Set([
  'NOT_A_REVIEWER',
  'VERIFICATION_CLOSED',
  'KEY_CHANGED',
  'SIGNATURE_INVALID',
  'BAD_NOTES',
  'DIRECTORY_UNAVAILABLE',
  'PERMISSIONS_CHANGED',
  'NOT_STARTED',
  'VERIFICATION_NOT_FOUND',
  'HEAD_CHANGED',
]);

function codeOf(error: unknown): string | undefined {
  return error instanceof AppError ? error.serverCode : undefined;
}

export function errorKey(error: unknown): string {
  const code = codeOf(error) ?? '';
  return KNOWN.has(code) ? code : 'FAILED';
}

/** The last entry's seq: what the reviewer loaded, so a start never skips a newer head. */
export function headSeq(state: Ready): number {
  return state.ready.opened.entries.at(-1)?.seq ?? 0;
}

/** Signs over the digest of exactly the notes it posts (A.3a); a changed snapshot is re-taken once. */
export function useDecision(
  state: Ready,
  unlocked: UnlockedKeys,
  seal: () => Promise<ReviewDraft>
) {
  const { reviews, archiveCrypto } = useServices();
  const verificationId = state.review.record.verificationId;

  const post = async (record: VerificationRecord, outcome: Outcome, draft: ReviewDraft) => {
    const identity = getAdminIdentity();
    if (identity === null || record.reviewedHead === null) throw new Error('not started');
    const signature = await archiveCrypto.signVerification(unlocked, {
      tenantId: identity.tenantId,
      verificationId,
      conversationId: state.ready.opened.conversation.conversationId,
      reviewedHead: record.reviewedHead,
      outcome,
      notesDigest: await notesDigest(draft.overall, draft.notes),
      snapshot: record.permissionSnapshot ?? [],
    });
    return reviews.decide(verificationId, { ...draft, outcome, signature });
  };

  return useMutation({
    mutationFn: async (outcome: Outcome) => {
      const draft = await seal();
      try {
        return await post(state.review.record, outcome, draft);
      } catch (error) {
        if (codeOf(error) !== 'PERMISSIONS_CHANGED') throw error;
        return post(await reviews.start(verificationId, headSeq(state)), outcome, draft);
      }
    },
  });
}
