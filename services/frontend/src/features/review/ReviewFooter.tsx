import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import { DecisionDialog } from './DecisionDialog';
import type { ReviewState } from './openReview';
import { errorKey, useDecision } from './useDecision';
import type { ReviewDraftState } from './useReviewDraft';

interface ReviewFooterProps {
  state: Extract<ReviewState, { status: 'ready' }>;
  unlocked: UnlockedKeys;
  draft: ReviewDraftState;
  onDecided: () => void;
}

/** Saving and deciding; a save is never audited, the decision always is (spec §10.7). */
export function ReviewFooter({ state, unlocked, draft, onDecided }: Readonly<ReviewFooterProps>) {
  const { t } = useTranslation();
  const [deciding, setDeciding] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const decision = useDecision(state, unlocked, draft.seal);
  const save = () => {
    setSaveFailed(false);
    draft.save().catch(() => setSaveFailed(true));
  };
  return (
    <section className="flex flex-wrap items-center gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
      <p className="flex-1 text-label text-fg-muted">
        {t(draft.dirty ? 'admin.review.unsaved' : 'admin.review.saved')}
      </p>
      {saveFailed && (
        <p role="alert" className="text-label text-fg-status-alert">
          {t('admin.review.error.SAVE_FAILED')}
        </p>
      )}
      <Button variant="compact" className="border border-border-card text-fg-body" onClick={save}>
        {t('admin.review.save')}
      </Button>
      <Button
        variant="compact"
        className="bg-accent text-accent-on"
        onClick={() => setDeciding(true)}
      >
        {t('admin.review.decide')}
      </Button>
      {deciding && (
        <DecisionDialog
          pending={decision.isPending}
          error={decision.isError ? errorKey(decision.error) : null}
          onDecide={(outcome) =>
            decision.mutate(outcome, {
              onSuccess: () => {
                draft.close();
                onDecided();
              },
            })
          }
          onCancel={() => setDeciding(false)}
        />
      )}
    </section>
  );
}
