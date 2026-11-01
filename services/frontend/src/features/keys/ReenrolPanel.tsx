import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { OwnKey, Reenrolled } from '@/domain/recording/recording.types';
import { Button } from '@/ui/primitives/Button';
import { NewKeyForm } from './NewKeyForm';
import { ReenrolWarning } from './ReenrolWarning';
import { StepUpPrompt } from './StepUpPrompt';
import { type ReenrolmentError, useReenrolment } from './useReenrolment';

const ERROR_KEYS: Record<Exclude<ReenrolmentError, 'stepUp'>, string> = {
  mismatch: 'admin.keys.passphraseMismatch',
  weak: 'admin.keys.passphraseWeak',
  failed: 'admin.keys.reenrol.failed',
  changed: 'admin.keys.reenrol.changed',
  ceremony: 'admin.keys.reenrol.ceremony',
};

interface ReenrolPanelProps {
  owner: KeyOwner;
  ownKey: OwnKey;
  onOpenKeyRecovery?: () => void;
}

function Result({
  done,
  onOpenKeyRecovery,
}: Readonly<{ done: Reenrolled; onOpenKeyRecovery?: () => void }>) {
  const { t } = useTranslation();
  const active = done.status === 'active';
  return (
    <section
      role="status"
      className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5"
    >
      <p className="text-note text-fg-body">
        {t(active ? 'admin.keys.reenrol.done' : 'admin.keys.reenrol.pending')}
      </p>
      <code className="text-body font-semibold text-fg-strong">{done.fingerprintDisplay}</code>
      {active && onOpenKeyRecovery && (
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          onClick={onOpenKeyRecovery}
        >
          {t('admin.keyRecovery.open')}
        </Button>
      )}
    </section>
  );
}

function ReenrolForm({ owner, ownKey, onOpenKeyRecovery }: Readonly<ReenrolPanelProps>) {
  const { t } = useTranslation();
  const { submit, error, pending, result } = useReenrolment(owner, ownKey.keyVersion);
  if (result !== null) return <Result done={result} onOpenKeyRecovery={onOpenKeyRecovery} />;
  if (error === 'stepUp') return <StepUpPrompt />;
  return (
    <NewKeyForm
      title={t('admin.keys.reenrol.submit')}
      body={t('admin.keys.enrolBody')}
      action={t('admin.keys.reenrol.submit')}
      pending={pending}
      error={error === null ? null : t(ERROR_KEYS[error])}
      onSubmit={(passphrase, confirmation) => void submit(passphrase, confirmation)}
    />
  );
}

/** "Forgot your passphrase?": a warning, a fresh second factor, then a new key (spec §9.6). */
export function ReenrolPanel(props: Readonly<ReenrolPanelProps>) {
  const { t } = useTranslation();
  const [stage, setStage] = useState<'idle' | 'warning' | 'stepUp' | 'form'>('idle');
  // Decided once, at Continue: a re-render 240 s later must not hide the new key's result.
  const proceed = () => setStage(hasFreshStepUp() ? 'form' : 'stepUp');

  if (stage === 'warning')
    return <ReenrolWarning onContinue={proceed} onCancel={() => setStage('idle')} />;
  if (stage === 'stepUp') return <StepUpPrompt />;
  if (stage === 'form') return <ReenrolForm {...props} />;
  return (
    <button
      type="button"
      className="self-start text-label font-medium text-fg-muted"
      onClick={() => setStage('warning')}
    >
      {t('admin.keys.reenrol.start')}
    </button>
  );
}
