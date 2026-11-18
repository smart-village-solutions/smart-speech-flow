import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { pinVault } from '@/features/keys/pinVault';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { type ReviewState, openReview } from './openReview';

export const REVIEW_PERMISSION = 'ssf.recording.review';
export const INBOX_QUERY = ['reviews', 'inbox'] as const;

export function useInbox() {
  const { reviews } = useServices();
  return useQuery({ queryKey: INBOX_QUERY, queryFn: ({ signal }) => reviews.inbox(signal) });
}

/** Keys and plaintext live in this state only, and go when the review closes. */
export function useReview(
  verificationId: string,
  unlocked: UnlockedKeys,
  version: number
): ReviewState {
  const { keyVault, archive, archiveCrypto, ceremonyCrypto, reviews } = useServices();
  const request = `${verificationId}:${version}`;
  const [result, setResult] = useState<{ request: string; state: ReviewState } | null>(null);

  useEffect(() => {
    let live = true;
    const identity = getAdminIdentity();
    const opening: Promise<ReviewState> =
      identity === null
        ? Promise.resolve({ status: 'unavailable' })
        : openReview(
            {
              archive,
              archiveCrypto,
              ceremonyCrypto,
              reviews,
              identity,
              ...pinVault(keyVault, identity),
            },
            verificationId,
            unlocked
          );
    const settle = (state: ReviewState) => {
      if (live) setResult({ request, state });
    };
    opening.then(settle, () => settle({ status: 'unavailable' }));
    return () => {
      live = false;
    };
  }, [
    keyVault,
    archive,
    archiveCrypto,
    ceremonyCrypto,
    reviews,
    verificationId,
    unlocked,
    request,
  ]);

  return result?.request === request ? result.state : { status: 'checking' };
}
