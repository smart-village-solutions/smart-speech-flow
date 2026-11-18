import { useMutation } from '@tanstack/react-query';
import { equalBytes } from '@/core/crypto/bytes';
import { getAdminIdentity, hasPermission } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { notesDigest } from '@/core/crypto/verification';
import { knownServerCode } from '@/core/http/AppError';
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

export function errorKey(error: unknown): string {
  return knownServerCode(error, KNOWN, 'FAILED');
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
  const { keyVault, reviews, archiveCrypto } = useServices();
  const verificationId = state.review.record.verificationId;

  const post = async (
    record: VerificationRecord,
    outcome: Outcome,
    draft: ReviewDraft,
    generation: number
  ) => {
    const identity = getAdminIdentity();
    if (identity === null || record.reviewedHead === null) throw new Error('not started');
    const checkVersion = () => {
      if (
        generation !== keyVault.generation() ||
        (state.ready.opened.requiredKeyVersions &&
          (!hasPermission('ssf.recording.review') ||
            record.verificationId !== verificationId ||
            record.reviewerSub !== identity.userSub ||
            !equalBytes(record.reviewerFingerprint, unlocked.fingerprint) ||
            record.reviewerKeyVersion !== state.review.record.reviewerKeyVersion ||
            keyVault.version(identity, record.reviewerKeyVersion) !== unlocked))
      )
        throw new Error('Assigned key changed');
    };
    checkVersion();
    const signature = await archiveCrypto.signVerification(unlocked, {
      tenantId: identity.tenantId,
      verificationId,
      conversationId: state.ready.opened.conversation.conversationId,
      reviewedHead: record.reviewedHead,
      outcome,
      notesDigest: await notesDigest(draft.overall, draft.notes),
      snapshot: record.permissionSnapshot ?? [],
    });
    checkVersion();
    return reviews.decide(verificationId, { ...draft, outcome, signature });
  };

  return useMutation({
    mutationFn: async (outcome: Outcome) => {
      const generation = keyVault.generation();
      const draft = await seal();
      try {
        return await post(state.review.record, outcome, draft, generation);
      } catch (error) {
        if (errorKey(error) !== 'PERMISSIONS_CHANGED') throw error;
        return post(
          await reviews.start(verificationId, headSeq(state)),
          outcome,
          draft,
          generation
        );
      }
    },
  });
}
