import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { KeyRecoveryBatch } from './KeyRecoveryBatch';
import { OwnFingerprint } from './OwnFingerprint';
import type { StaffScreenProps } from './RecoveryRequestsScreen';
import { RecoveryShell } from './RecoveryShell';
import { RecoveryLocked } from './RecoveryLocked';
import { RequestDetail } from './RequestDetail';
import { SummaryList } from './SummaryList';
import { KEY_RECOVERY_VIEW } from './useKeyRecovery';
import { useRecoveryRequests } from './useRecovery';

interface HomeProps {
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
  onOpen: (requestId: string) => void;
}

interface FilingProps {
  fresh: boolean;
  keys: UnlockedKeys | null;
  again: boolean;
  onOpenKeys: () => void;
}

/** Step-up before the unlock, so its redirect never wipes unlocked keys (§9.5). */
function Filing({ fresh, keys, again, onOpenKeys }: Readonly<FilingProps>) {
  if (!fresh) return <StepUpPrompt returnTo={KEY_RECOVERY_VIEW} />;
  if (keys === null) return <RecoveryLocked onOpenKeys={onOpenKeys} />;
  return <KeyRecoveryBatch keys={keys} again={again} />;
}

/** One key recovery at a time: the batch is offered only while none is open (§9.6). */
function Home({ keys, onOpenKeys, onOpen }: Readonly<HomeProps>) {
  const { t } = useTranslation();
  // Read once: a later re-render must not swap a half-typed reason for the prompt.
  const [fresh] = useState(hasFreshStepUp);
  const requests = useRecoveryRequests('key_recovery');
  if (requests.isError)
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.recovery.unavailable')}
      </p>
    );
  if (!requests.data) return null;
  const open = requests.data.some((row) => row.status === 'open');
  const again = requests.data.some((row) => row.status === 'completed');
  return (
    <>
      {!open && <Filing fresh={fresh} keys={keys} again={again} onOpenKeys={onOpenKeys} />}
      {/* The custodians call while the request is open: the value they ask for stays here. */}
      {open && keys !== null && <OwnFingerprint keys={keys} />}
      {open && keys === null && <RecoveryLocked onOpenKeys={onOpenKeys} />}
      {requests.data.length > 0 && <SummaryList rows={requests.data} empty="" onOpen={onOpen} />}
    </>
  );
}

/** An employee's own key recovery: request, follow, combine (spec §9.6). */
export function KeyRecoveryScreen({
  onBack,
  onOpenKeys,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<StaffScreenProps>) {
  const { t } = useTranslation();
  const unlocked = useUnlockedKeys();
  const [open, setOpen] = useState<string | null>(null);
  const home = () => setOpen(null);

  return (
    <RecoveryShell
      onBack={open === null ? onBack : home}
      onHome={onBack}
      onSignOut={onSignOut}
      accountUrl={accountUrl}
      studioUrl={studioUrl}
      title={t('admin.keyRecovery.title')}
      intro={t('admin.keyRecovery.intro')}
    >
      {open === null && <Home keys={unlocked} onOpenKeys={onOpenKeys} onOpen={setOpen} />}
      {open !== null && (
        <RequestDetail
          key={open}
          requestId={open}
          keys={unlocked}
          onOpenKeys={onOpenKeys}
          onCancelled={home}
        />
      )}
    </RecoveryShell>
  );
}
