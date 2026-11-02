import { useState } from 'react';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { OpeningState } from '@/features/archive/OpeningState';
import { ReadyReview } from './ReadyReview';
import { useReview } from './useReviews';

interface ReviewScreenProps {
  verificationId: string;
  unlocked: UnlockedKeys;
  onDone: (outcome: 'decided' | 'declined') => void;
}

/** Shown only once every check of spec §10.6 has passed, as the archive viewer is. */
export function ReviewScreen({ verificationId, unlocked, onDone }: Readonly<ReviewScreenProps>) {
  const [version, setVersion] = useState(0);
  const state = useReview(verificationId, unlocked, version);
  if (state.status !== 'ready')
    return <OpeningState state={state} unavailable="admin.review.unavailable" />;
  return (
    <ReadyReview
      key={state.review.record.status}
      state={state}
      unlocked={unlocked}
      onStarted={() => setVersion((value) => value + 1)}
      onDone={onDone}
    />
  );
}
