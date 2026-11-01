import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { faultKey } from './faults';
import { OwnFingerprint } from './OwnFingerprint';
import { KEY_RECOVERY_VIEW, useOwnCandidates } from './useKeyRecovery';
import { useFileRequest } from './useRecovery';

const MAX_REASON = 1000;

interface KeyRecoveryBatchProps {
  keys: UnlockedKeys;
  /** A request completed before: this is the next batch. */
  again: boolean;
}

/** The next batch, signed as a key recovery once the employee gives a reason (§9.6). */
export function KeyRecoveryBatch({ keys, again }: Readonly<KeyRecoveryBatchProps>) {
  const { t } = useTranslation();
  const own = useOwnCandidates(true);
  const filing = useFileRequest(keys, 'key_recovery');
  const [reason, setReason] = useState('');

  if (own.isError)
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.recovery.unavailable')}
      </p>
    );
  if (!own.data) return null;
  const { conversations, remaining } = own.data;
  if (conversations.length === 0)
    return <p className="text-note text-fg-muted">{t('admin.keyRecovery.none')}</p>;
  if (filing.fault === 'step_up') return <StepUpPrompt returnTo={KEY_RECOVERY_VIEW} />;

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <p className="text-body font-semibold text-fg-strong">
        {t('admin.keyRecovery.batch', { count: conversations.length })}
      </p>
      {remaining.conversations > 0 && (
        <p className="text-label text-fg-muted">
          {t('admin.keyRecovery.remaining', { conversations: remaining.conversations })}
        </p>
      )}
      <OwnFingerprint keys={keys} />
      <label className="flex flex-col gap-1.5 text-meta font-medium text-fg-muted">
        {t('admin.keyRecovery.reason')}
        <textarea
          rows={4}
          maxLength={MAX_REASON}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="rounded-xl border border-border-card px-3 py-2.5 text-body text-fg-body"
        />
      </label>
      <Button
        className="self-start bg-accent text-accent-on"
        disabled={filing.pending || reason.trim() === ''}
        onClick={() => void filing.file({ reason: reason.trim(), candidates: conversations })}
      >
        {t(again ? 'admin.keyRecovery.next' : 'admin.keyRecovery.file')}
      </Button>
      {filing.fault !== null && (
        <p role="alert" className="text-label text-fg-status-alert">
          {t(faultKey(filing.fault))}
        </p>
      )}
    </section>
  );
}
