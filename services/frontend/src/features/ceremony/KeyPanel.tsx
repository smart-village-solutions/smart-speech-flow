import { useState } from 'react';
import { hasPermission } from '@/app/auth/keycloak';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { CeremonyState, RecoveryKey } from '@/domain/recovery/recovery.types';
import { LastFailedNotice } from './LastFailedNotice';
import { OpenCeremony } from './OpenCeremony';
import { RecoveryKeyCard } from './RecoveryKeyCard';
import { ReshareForm } from './ReshareForm';
import { TENANT_MANAGE } from './useCeremony';

interface KeyPanelProps {
  recoveryKey: RecoveryKey;
  state: CeremonyState;
  owner: KeyOwner;
  onOpenKeys: () => void;
}

/** An active key, and the change of its custodians when one is started or runs (spec §9.7). */
export function KeyPanel({ recoveryKey, state, owner, onOpenKeys }: Readonly<KeyPanelProps>) {
  const [changing, setChanging] = useState(false);
  const mayStart = hasPermission(TENANT_MANAGE) && state.ceremony === null;

  return (
    <>
      <RecoveryKeyCard
        recoveryKey={recoveryKey}
        onReshare={mayStart && !changing ? () => setChanging(true) : undefined}
      />
      {state.lastFailed !== null && <LastFailedNotice failed={state.lastFailed} reshared />}
      {mayStart && changing && (
        <ReshareForm
          tenantId={owner.tenantId}
          recoveryKey={recoveryKey}
          onCancel={() => setChanging(false)}
        />
      )}
      {state.ceremony !== null && (
        <OpenCeremony
          ceremony={state.ceremony}
          chain={state.chain}
          owner={owner}
          onOpenKeys={onOpenKeys}
        />
      )}
    </>
  );
}
