import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, CeremonyDealer } from '@/domain/recovery/recovery.types';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
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

function EarlierKeyForm({
  fingerprint,
  failed,
  onUnlock,
}: Readonly<{ fingerprint: string; failed: boolean; onUnlock: (passphrase: string) => void }>) {
  const { t } = useTranslation();
  const [passphrase, setPassphrase] = useState('');
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    onUnlock(passphrase);
  };
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.ceremony.reshare.retiredKey')} <code>{fingerprint}</code>
      </p>
      <TextField
        type="password"
        autoComplete="off"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
        error={failed ? t('admin.ceremony.reshare.unlockFailed') : null}
      />
      <Button type="submit" variant="compact" className="self-start bg-accent text-accent-on">
        {t('admin.ceremony.reshare.unlockRetired')}
      </Button>
    </form>
  );
}

type DealerActions = ReturnType<typeof useDealerActions>;

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
  // A locked vault is unlocked on the keys screen; only a key it does not hold is asked for here.
  if (keys === null) {
    return (
      <>
        <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.unlockFirst')}</p>
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          onClick={onOpenKeys}
        >
          {t('admin.ceremony.openKeys')}
        </Button>
      </>
    );
  }
  if (actions.needsEarlierKey && actions.served !== null) {
    return (
      <EarlierKeyForm
        fingerprint={actions.served.fingerprintDisplay}
        failed={actions.unlockFailed}
        onUnlock={(passphrase) => void actions.unlockEarlier(passphrase)}
      />
    );
  }
  if (!actions.ready) return null;
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
  const actions = useDealerActions(ceremony, facts, dealer, owner, keys);
  // Asked first and latched: a redirect later would lose the ticks and an unlocked earlier key.
  const [fresh] = useState(() => hasFreshStepUp());
  const dealt = ceremony.dealings.some((dealing) => dealing.dealerIndex === dealer.dealerIndex);

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
