import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { CandidateList } from './CandidateList';
import { ThresholdSelect } from './ThresholdSelect';
import { CEREMONY_VIEW } from './useCeremony';
import { type StartError, useStartCeremony } from './useStartCeremony';

const ERROR_KEYS: Record<Exclude<StartError, 'stepUp'>, string> = {
  invalid: 'admin.ceremony.startInvalid',
  failed: 'admin.ceremony.startFailed',
};

/** The tenant administrator names the custodians and the threshold (spec §9.1, §9.2). */
export function StartForm({ tenantId }: Readonly<{ tenantId: string }>) {
  const { t } = useTranslation();
  const { start, error, pending } = useStartCeremony(tenantId);
  const [chosen, setChosen] = useState<string[]>([]);
  const [k, setK] = useState(2);
  const [paper, setPaper] = useState(true);

  if (error === 'stepUp') return <StepUpPrompt returnTo={CEREMONY_VIEW} />;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void start({ k, custodians: chosen, paper });
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.ceremony.startTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.startBody')}</p>
      <CandidateList chosen={chosen} onChange={setChosen} />
      <ThresholdSelect k={k} onChange={setK} />
      <p className="text-meta text-fg-muted">{t(k === 1 ? 'admin.ceremony.modeStandard' : 'admin.ceremony.modeEnhanced')}</p>
      <Checkbox checked={paper} onCheckedChange={setPaper}>
        {t('admin.ceremony.paperLabel')}
      </Checkbox>
      {error !== null && (
        <p role="alert" className="text-meta text-fg-status-alert">
          {t(ERROR_KEYS[error])}
        </p>
      )}
      <Button
        type="submit"
        variant="compact"
        className="self-start bg-accent text-accent-on"
        disabled={pending || chosen.length < k + 1}
      >
        {t(pending ? 'admin.ceremony.startPending' : 'admin.ceremony.startAction')}
      </Button>
    </form>
  );
}
