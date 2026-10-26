import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, CeremonyParticipant } from '@/domain/recovery/recovery.types';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { StepAlert } from './StepAlert';
import { CEREMONY_VIEW } from './useCeremony';
import { useCustodianActions } from './useCustodianActions';

interface CustodianStepsProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
  participant: CeremonyParticipant;
  keys: UnlockedKeys;
}

function nextStep(ceremony: Readonly<Ceremony>, index: number): 'deal' | 'confirm' | 'wait' {
  if (ceremony.status === 'dealing') {
    return ceremony.dealings.some((dealing) => dealing.dealerIndex === index) ? 'wait' : 'deal';
  }
  return ceremony.confirmed.includes(index) ? 'wait' : 'confirm';
}

/** A custodian deals once, then checks everything and signs the transcript (spec §9.2 steps 3–6). */
export function CustodianSteps({ ceremony, facts, participant, keys }: Readonly<CustodianStepsProps>) {
  const { t } = useTranslation();
  const actions = useCustodianActions(ceremony, facts, participant, keys);
  const [compared, setCompared] = useState(false);
  const step = nextStep(ceremony, participant.holderIndex);

  if (actions.error === 'stepUp') return <StepUpPrompt returnTo={CEREMONY_VIEW} />;

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.ceremony.custodianTitle')}</h2>
      {step === 'wait' && <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.waitForOthers')}</p>}
      {step === 'deal' && (
        <>
          <Checkbox checked={compared} onCheckedChange={setCompared}>
            {t('admin.ceremony.compareAttest')}
          </Checkbox>
          <Button
            variant="compact"
            className="self-start bg-accent text-accent-on"
            disabled={!compared || actions.pending}
            onClick={() => void actions.deal()}
          >
            {t(actions.pending ? 'admin.ceremony.working' : 'admin.ceremony.dealAction')}
          </Button>
        </>
      )}
      {step === 'confirm' && (
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          disabled={actions.pending}
          onClick={() => void actions.confirm()}
        >
          {t(actions.pending ? 'admin.ceremony.working' : 'admin.ceremony.confirmAction')}
        </Button>
      )}
      {actions.error !== null && <StepAlert error={actions.error} />}
    </section>
  );
}
