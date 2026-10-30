import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, CeremonyDealer } from '@/domain/recovery/recovery.types';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { type DealerActions, KeyGate } from './DealerKeyGate';
import { NewHolderTicks } from './NewHolderTicks';
import { StepAlert } from './StepAlert';
import { CEREMONY_VIEW, allTicked } from './useCeremony';
import { useDealerActions } from './useDealerActions';

interface DealerStepsProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
  dealer: CeremonyDealer;
  owner: KeyOwner;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
}

interface DealingPartProps {
  ceremony: Ceremony;
  actions: DealerActions;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
}

/** Before dealing: unlock the listed key, tick every new fingerprint, deal. */
function DealingPart({ ceremony, actions, keys, onOpenKeys }: Readonly<DealingPartProps>) {
  const { t } = useTranslation();
  const [ticked, setTicked] = useState<Map<number, Bytes>>(new Map());
  if (!actions.ready) return <KeyGate actions={actions} keys={keys} onOpenKeys={onOpenKeys} />;
  return (
    <>
      <NewHolderTicks participants={ceremony.participants} ticked={ticked} onChange={setTicked} />
      <Button
        variant="compact"
        className="self-start bg-accent text-accent-on"
        disabled={!allTicked(ceremony.participants, ticked) || actions.pending}
        onClick={() => void actions.deal()}
      >
        {t(actions.pending ? 'admin.ceremony.working' : 'admin.ceremony.reshare.deal')}
      </Button>
    </>
  );
}

/** An old custodian hands its share over to the new holders (spec §9.7). */
export function DealerSteps({
  ceremony,
  facts,
  dealer,
  owner,
  keys,
  onOpenKeys,
}: Readonly<DealerStepsProps>) {
  const { t } = useTranslation();
  // Asked first and latched: a redirect later would lose the ticks and an unlocked earlier key.
  const [fresh] = useState(() => hasFreshStepUp());
  const dealt = ceremony.dealings.some((dealing) => dealing.dealerIndex === dealer.dealerIndex);
  const actions = useDealerActions(ceremony, facts, dealer, owner, keys, fresh && !dealt);

  if (actions.error === 'stepUp' || (!dealt && !fresh))
    return <StepUpPrompt returnTo={CEREMONY_VIEW} />;

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
      <h2 className="text-body font-semibold text-fg-strong">
        {t('admin.ceremony.reshare.dealerTitle')}
      </h2>
      {dealt ? (
        <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.waitForOthers')}</p>
      ) : (
        <DealingPart ceremony={ceremony} actions={actions} keys={keys} onOpenKeys={onOpenKeys} />
      )}
      {actions.error !== null && <StepAlert error={actions.error} />}
    </section>
  );
}
