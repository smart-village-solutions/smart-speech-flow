import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { ApprovalDetail } from '@/domain/recovery/requests.types';
import { formatDate, formatTimeRange } from '@/features/archive/format';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { faultKey } from './faults';
import { ReviewActions } from './ReviewActions';
import { Chip } from './StatusChip';
import { RECOVERY_APPROVALS_VIEW, useApprove } from './useRecovery';

function Conversations({ detail }: Readonly<{ detail: ApprovalDetail }>) {
  const { i18n } = useTranslation();
  const seen = new Map(detail.keys.map((k) => [k.conversationId, k]));
  return (
    <ul className="divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card">
      {[...seen.values()].map((k) => (
        <li key={k.conversationId} className="flex items-center gap-3 px-4 py-3">
          <span className="flex-1 text-note font-semibold text-fg-strong">
            {k.employeeName ?? k.employeeSub}
          </span>
          <span className="text-label text-fg-muted">
            {formatDate(k.startedAt, i18n.language)} ·{' '}
            {formatTimeRange(k.startedAt, k.endedAt, i18n.language)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A check of ours says "do not approve" and offers nothing; a refusal or an outage may be retried. */
function Fault({ fault, onRetry }: Readonly<{ fault: string; onRetry: () => void }>) {
  const { t } = useTranslation();
  const retryable = fault === 'unavailable' || fault.startsWith('refused.');
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5"
    >
      <p className="text-note text-fg-status-alert">{t(faultKey(fault))}</p>
      {retryable && (
        <button
          type="button"
          className="self-start text-label font-medium text-fg-link"
          onClick={onRetry}
        >
          {t('admin.recovery.retry')}
        </button>
      )}
    </div>
  );
}

interface ApprovalReviewProps {
  detail: ApprovalDetail;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
  onDecided: () => void;
  onRetry: () => void;
}

/**
 * The fingerprint shown is computed here from the served keys, never read from the
 * server; the step-up comes before the unlock, so its redirect wipes nothing (§9.5).
 */
export function ApprovalReview({
  detail,
  keys,
  onOpenKeys,
  onDecided,
  onRetry,
}: Readonly<ApprovalReviewProps>) {
  const { t, i18n } = useTranslation();
  const review = useApprove(detail, keys);
  // Not while an approval computes: its progress re-renders must not offer a redirect.
  const stale = review.fault === 'step_up' || (!review.pending && !hasFreshStepUp());
  const decide = async (work: Promise<boolean>) => {
    if (await work) onDecided();
  };
  const retry = () => {
    review.retry();
    onRetry();
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5 rounded-2xl border border-border-card bg-surface-card p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-thanks font-semibold text-fg-strong">
            {detail.requesterName ?? detail.requesterSub}
          </h2>
          <Chip label={t(`admin.recovery.kind.${detail.kind}`)} tone="muted" />
        </div>
        <p className="whitespace-pre-wrap text-note text-fg-body">{detail.reason}</p>
        <p className="text-label text-fg-muted">
          {formatDate(detail.createdAt, i18n.language)} –{' '}
          {formatDate(detail.expiresAt, i18n.language)}
        </p>
      </div>
      <div className="flex flex-col gap-2 rounded-2xl border border-border-status bg-surface-card p-5">
        <p className="text-meta font-medium text-fg-muted">
          {t('admin.recovery.approve.fingerprint')}
        </p>
        <code className="text-body font-semibold text-fg-strong">
          {review.fingerprint === null ? '…' : displayFingerprint(review.fingerprint)}
        </code>
        <p className="text-label text-fg-muted">{t('admin.recovery.approve.fingerprintHint')}</p>
        {detail.kind === 'key_recovery' && (
          <p className="text-label font-semibold text-fg-body">
            {t('admin.recovery.approve.askFiled')}
          </p>
        )}
      </div>
      <Conversations detail={detail} />
      {stale && <StepUpPrompt returnTo={RECOVERY_APPROVALS_VIEW} />}
      {!stale && review.fault !== null && <Fault fault={review.fault} onRetry={retry} />}
      {!stale && review.fault === null && (
        <ReviewActions
          fingerprint={review.fingerprint}
          keys={keys}
          pending={review.pending}
          onApprove={(confirmed) => void decide(review.approve(confirmed))}
          onDecline={(reason) => void decide(review.decline(reason))}
          onOpenKeys={onOpenKeys}
        />
      )}
      {review.pending && review.progress !== null && (
        <p role="status" className="text-label text-fg-muted">
          {t('admin.keyRecovery.progress', {
            done: review.progress.done,
            total: review.progress.total,
          })}
        </p>
      )}
    </section>
  );
}
