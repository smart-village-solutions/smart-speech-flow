import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { Button } from '@/ui/primitives/Button';
import { NewRequestForm } from './NewRequestForm';
import { RecoveryShell } from './RecoveryShell';
import { RecoveryLocked } from './RecoveryLocked';
import { RequestDetail } from './RequestDetail';
import { SummaryList } from './SummaryList';
import { RECOVERY_REQUESTS_VIEW, useRecoveryRequests } from './useRecovery';

export interface StaffScreenProps {
  onBack: () => void;
  onOpenKeys: () => void;
  onSignOut: () => void;
  /** The employee's key recovery; offered where a screen points to it (spec §9.6). */
  onOpenKeyRecovery?: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

type View = { kind: 'list' } | { kind: 'new' } | { kind: 'detail'; requestId: string };

function RequestList({
  onNew,
  onOpen,
}: Readonly<{ onNew: () => void; onOpen: (id: string) => void }>) {
  const { t } = useTranslation();
  const requests = useRecoveryRequests('access');
  return (
    <>
      <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={onNew}>
        {t('admin.recovery.new.action')}
      </Button>
      {requests.isError && (
        <p role="alert" className="text-note text-fg-status-alert">
          {t('admin.recovery.unavailable')}
        </p>
      )}
      {requests.data && (
        <SummaryList
          rows={requests.data}
          empty={t('admin.recovery.requests.empty')}
          onOpen={onOpen}
        />
      )}
    </>
  );
}

interface NewRequestProps {
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
  onFiled: () => void;
}

/** Step-up before the unlock, so its redirect never wipes unlocked keys (§9.5). */
function NewRequest({ keys, onOpenKeys, onFiled }: Readonly<NewRequestProps>) {
  if (!hasFreshStepUp()) return <StepUpPrompt returnTo={RECOVERY_REQUESTS_VIEW} />;
  if (keys === null) return <RecoveryLocked onOpenKeys={onOpenKeys} />;
  return <NewRequestForm keys={keys} onFiled={onFiled} />;
}

/** A supervisor's exceptional-access requests (spec §9.5). */
export function RecoveryRequestsScreen({
  onBack,
  onOpenKeys,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<StaffScreenProps>) {
  const { t } = useTranslation();
  const unlocked = useUnlockedKeys();
  const [view, setView] = useState<View>({ kind: 'list' });
  const toList = () => setView({ kind: 'list' });

  return (
    <RecoveryShell
      onBack={view.kind === 'list' ? onBack : toList}
      onHome={onBack}
      onSignOut={onSignOut}
      accountUrl={accountUrl}
      studioUrl={studioUrl}
      title={t('admin.recovery.requests.title')}
      intro={t('admin.recovery.requests.intro')}
    >
      {view.kind === 'list' && (
        <RequestList
          onNew={() => setView({ kind: 'new' })}
          onOpen={(requestId) => setView({ kind: 'detail', requestId })}
        />
      )}
      {view.kind === 'new' && (
        <NewRequest keys={unlocked} onOpenKeys={onOpenKeys} onFiled={toList} />
      )}
      {view.kind === 'detail' && (
        <RequestDetail
          key={view.requestId}
          requestId={view.requestId}
          keys={unlocked}
          onOpenKeys={onOpenKeys}
          onCancelled={toList}
        />
      )}
    </RecoveryShell>
  );
}
