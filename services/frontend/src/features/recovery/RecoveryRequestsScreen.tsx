import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import { NewRequestForm } from './NewRequestForm';
import { RecoveryLocked } from './RecoveryLocked';
import { RequestDetail } from './RequestDetail';
import { SummaryList } from './SummaryList';
import { RECOVERY_REQUESTS_VIEW, useRecoveryRequests } from './useRecovery';

export interface StaffScreenProps {
  onBack: () => void;
  onOpenKeys: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

type View = { kind: 'list' } | { kind: 'new' } | { kind: 'detail'; requestId: string };

function RequestList({
  onNew,
  onOpen,
}: Readonly<{ onNew: () => void; onOpen: (id: string) => void }>) {
  const { t } = useTranslation();
  const requests = useRecoveryRequests();
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
  const { openFeedback } = useFeedback();
  const unlocked = useUnlockedKeys();
  const [view, setView] = useState<View>({ kind: 'list' });
  useScreenLocale('de');
  const toList = () => setView({ kind: 'list' });

  return (
    <ScreenShell>
      <AdminHeader
        onBack={view.kind === 'list' ? onBack : toList}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">
            {t('admin.recovery.requests.title')}
          </h1>
          <p className="text-note leading-chat text-fg-muted">
            {t('admin.recovery.requests.intro')}
          </p>
        </div>
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
      </div>
    </ScreenShell>
  );
}
