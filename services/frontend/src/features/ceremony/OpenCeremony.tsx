import { useTranslation } from 'react-i18next';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, ServedChain } from '@/domain/recovery/recovery.types';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { Button } from '@/ui/primitives/Button';
import { AbortButton } from './AbortButton';
import { CustodianSteps } from './CustodianSteps';
import { DealerSteps } from './DealerSteps';
import { PaperDealerPanel } from './PaperDealerPanel';
import { PaperDevicePanel } from './PaperDevicePanel';
import { ParticipantList } from './ParticipantList';
import { ceremonyFacts, useCertifiedChain } from './useCeremony';

interface OpenCeremonyProps {
  ceremony: Ceremony;
  /** The key's generations so far, served while a resharing runs (spec §9.7). */
  chain: ServedChain | null;
  owner: KeyOwner;
  onOpenKeys: () => void;
}

interface RolesProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
  owner: KeyOwner;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
}

/** A new holder, or a first ceremony's custodian: unlock, then deal and sign. */
function HolderRole({ ceremony, facts, owner, keys, onOpenKeys }: Readonly<RolesProps>) {
  const { t } = useTranslation();
  const participant = ceremony.participants.find((p) => p.kind === 'custodian' && p.holderRef === owner.userSub);
  if (participant === undefined) return null;
  if (keys !== null) return <CustodianSteps ceremony={ceremony} facts={facts} participant={participant} keys={keys} />;
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
      <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.unlockFirst')}</p>
      <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={onOpenKeys}>
        {t('admin.ceremony.openKeys')}
      </Button>
    </section>
  );
}

/** An old custodian handing its share over in a resharing (spec §9.7). */
function DealerRole({ ceremony, facts, owner, keys, onOpenKeys }: Readonly<RolesProps>) {
  const dealer = ceremony.dealers.find((d) => d.kind === 'custodian' && d.holderRef === owner.userSub);
  if (ceremony.kind !== 'resharing' || dealer === undefined) return null;
  return (
    <DealerSteps ceremony={ceremony} facts={facts} dealer={dealer} owner={owner} keys={keys} onOpenKeys={onOpenKeys} />
  );
}

/** The starter's browser: typing in old sheets that deal, and printing new ones. */
function DeviceRole({ ceremony, facts, owner }: Readonly<RolesProps>) {
  if (ceremony.startedBy !== owner.userSub) return null;
  const sheetsDeal = ceremony.status === 'dealing' && ceremony.dealers.some((d) => d.kind === 'paper');
  const hasPaper = ceremony.participants.some((p) => p.kind === 'paper');
  return (
    <>
      {sheetsDeal && <PaperDealerPanel ceremony={ceremony} facts={facts} />}
      {hasPaper && <PaperDevicePanel ceremony={ceremony} facts={facts} />}
    </>
  );
}

/** A ceremony or resharing in progress: who takes part, and this user's own part in it. */
export function OpenCeremony({ ceremony, chain, owner, onOpenKeys }: Readonly<OpenCeremonyProps>) {
  const { t } = useTranslation();
  const keys = useUnlockedKeys();
  const certified = useCertifiedChain(owner.tenantId, ceremony.kind === 'resharing' ? chain : null);
  const facts = ceremonyFacts(owner.tenantId, ceremony, certified.previous);
  const takesPart =
    ceremony.startedBy === owner.userSub ||
    ceremony.participants.some((p) => p.kind === 'custodian' && p.holderRef === owner.userSub) ||
    ceremony.dealers.some((d) => d.kind === 'custodian' && d.holderRef === owner.userSub);

  return (
    <>
      <ParticipantList ceremony={ceremony} facts={facts} />
      {certified.pending ? (
        <p className="text-note text-fg-muted">{t('admin.ceremony.reshare.chainPending')}</p>
      ) : (
        <>
          <DealerRole ceremony={ceremony} facts={facts} owner={owner} keys={keys} onOpenKeys={onOpenKeys} />
          <HolderRole ceremony={ceremony} facts={facts} owner={owner} keys={keys} onOpenKeys={onOpenKeys} />
          <DeviceRole ceremony={ceremony} facts={facts} owner={owner} keys={keys} onOpenKeys={onOpenKeys} />
        </>
      )}
      {takesPart && <AbortButton ceremonyId={ceremony.ceremonyId} reason="cancelled" />}
    </>
  );
}
