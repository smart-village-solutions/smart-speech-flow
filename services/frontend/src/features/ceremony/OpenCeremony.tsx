import { useTranslation } from 'react-i18next';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { Button } from '@/ui/primitives/Button';
import { AbortButton } from './AbortButton';
import { CustodianSteps } from './CustodianSteps';
import { PaperDevicePanel } from './PaperDevicePanel';
import { ParticipantList } from './ParticipantList';
import { ceremonyFacts } from './useCeremony';

interface OpenCeremonyProps {
  ceremony: Ceremony;
  owner: KeyOwner;
  onOpenKeys: () => void;
}

/** A ceremony in progress: who takes part, and this user's own part in it. */
export function OpenCeremony({ ceremony, owner, onOpenKeys }: Readonly<OpenCeremonyProps>) {
  const { t } = useTranslation();
  const keys = useUnlockedKeys();
  const facts = ceremonyFacts(owner.tenantId, ceremony);
  const participant = ceremony.participants.find((p) => p.kind === 'custodian' && p.holderRef === owner.userSub);
  const isStarter = ceremony.startedBy === owner.userSub;
  const hasPaper = ceremony.participants.some((p) => p.kind === 'paper');

  return (
    <>
      <ParticipantList ceremony={ceremony} facts={facts} />
      {participant && keys === null && (
        <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
          <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.unlockFirst')}</p>
          <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={onOpenKeys}>
            {t('admin.ceremony.openKeys')}
          </Button>
        </section>
      )}
      {participant && keys !== null && (
        <CustodianSteps ceremony={ceremony} facts={facts} participant={participant} keys={keys} />
      )}
      {isStarter && hasPaper && <PaperDevicePanel ceremony={ceremony} facts={facts} />}
      {(participant || isStarter) && <AbortButton ceremonyId={ceremony.ceremonyId} reason="cancelled" />}
    </>
  );
}
