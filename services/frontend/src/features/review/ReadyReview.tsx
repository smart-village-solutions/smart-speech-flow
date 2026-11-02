import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import { MAX_OVERALL } from '@/domain/review/findings';
import { EntryCard } from '@/features/archive/EntryCard';
import { ViewerHeader } from '@/features/archive/ViewerHeader';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';
import { Button } from '@/ui/primitives/Button';
import { Textarea } from '@/ui/primitives/Textarea';
import { NoteEditor } from './NoteEditor';
import type { ReviewState } from './openReview';
import { ReviewFooter } from './ReviewFooter';
import { errorKey, headSeq } from './useDecision';
import { useReviewDraft } from './useReviewDraft';

interface ReadyReviewProps {
  state: Extract<ReviewState, { status: 'ready' }>;
  unlocked: UnlockedKeys;
  onStarted: () => void;
  onDone: (outcome: 'decided' | 'declined') => void;
}

/** One assignment: every stage read-only, with the reviewer's notes beside each message. */
export function ReadyReview({ state, unlocked, onStarted, onDone }: Readonly<ReadyReviewProps>) {
  const { t } = useTranslation();
  const { reviews } = useServices();
  const draft = useReviewDraft(state);
  const [declining, setDeclining] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const { record, requester } = state.review;
  const { opened, view, keys, stamps } = state.ready;
  const started = record.status === 'in_review';
  const head = record.reviewedHeadSeq ?? 0;
  const act = (work: Promise<unknown>, then: () => void) => {
    setFailure(null);
    work.then(then, (error: unknown) => {
      const code = errorKey(error);
      setFailure(code);
      // The conversation grew since it was loaded: reload it, then start on the new head.
      if (code === 'HEAD_CHANGED') onStarted();
    });
  };

  return (
    <>
      <ViewerHeader
        conversation={opened.conversation}
        header={view.header}
        stamps={stamps}
        lastSeq={headSeq(state)}
      />
      <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
        <p className="text-label text-fg-muted">
          {t('admin.review.assignedBy', { name: state.review.requesterName ?? record.requestedBy })}
        </p>
        {requester && (
          <code className="text-label text-fg-strong">
            {displayFingerprint(requester.fingerprint)}
          </code>
        )}
        {failure !== null && (
          <p role="alert" className="text-label text-fg-status-alert">
            {t(`admin.review.error.${failure}`)}
          </p>
        )}
        {!started && (
          <div className="flex gap-3">
            <Button
              variant="compact"
              className="bg-accent text-accent-on"
              onClick={() => act(reviews.start(record.verificationId, headSeq(state)), onStarted)}
            >
              {t('admin.review.start')}
            </Button>
            <button
              type="button"
              className="text-label font-medium text-fg-muted"
              onClick={() => setDeclining(true)}
            >
              {t('admin.review.decline')}
            </button>
          </div>
        )}
      </section>
      <ol className="flex flex-col">
        {view.entries.map((entry) => (
          <EntryCard key={entry.entry.entryId} view={entry} opened={opened} keys={keys}>
            {started && entry.entry.seq > head && (
              <p className="text-meta text-fg-muted">{t('admin.review.afterHead')}</p>
            )}
            {started && entry.entry.seq <= head && (
              <NoteEditor
                findings={draft.findings.get(entry.entry.entryId) ?? []}
                onChange={(next) => draft.setEntry(entry.entry.entryId, next)}
              />
            )}
          </EntryCard>
        ))}
      </ol>
      {started && (
        <>
          <label className="flex flex-col gap-1.5 rounded-2xl border border-border-card bg-surface-card p-5 text-label font-medium text-fg-body">
            {t('admin.review.overall')}
            <Textarea
              variant="field"
              rows={6}
              maxLength={MAX_OVERALL}
              value={draft.overall}
              onChange={(event) => draft.setOverall(event.target.value)}
            />
            <span className="self-end text-meta text-fg-muted">
              {t('admin.review.overallCount', { used: draft.overall.length })}
            </span>
          </label>
          <ReviewFooter
            state={state}
            unlocked={unlocked}
            draft={draft}
            onDecided={() => onDone('decided')}
          />
        </>
      )}
      <ConfirmDialog
        open={declining}
        title={t('admin.review.declineTitle')}
        body={t('admin.review.declineBody')}
        confirmLabel={t('admin.review.declineConfirm')}
        cancelLabel={t('admin.review.cancel')}
        onConfirm={() =>
          act(reviews.decline(record.verificationId), () => {
            draft.close();
            onDone('declined');
          })
        }
        onCancel={() => setDeclining(false)}
      />
    </>
  );
}
