import { useTranslation } from 'react-i18next';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { EnrolForm } from './EnrolForm';
import { FingerprintCard } from './FingerprintCard';
import { ReenrolPanel } from './ReenrolPanel';
import { StepUpPrompt } from './StepUpPrompt';
import { UnlockForm } from './UnlockForm';
import { useOwnKey, useUnlockedKeys } from './useKeys';

function KeysPanel({ onOpenKeyRecovery }: Readonly<{ onOpenKeyRecovery?: () => void }>) {
  const { t } = useTranslation();
  const owner = getAdminIdentity();
  const ownKey = useOwnKey();
  const unlocked = useUnlockedKeys();

  if (owner === null || ownKey.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.keys.unavailable')}
      </p>
    );
  }
  if (ownKey.isPending) return null;
  if (ownKey.data === null) {
    if (unlocked !== null) return <FingerprintCard keys={unlocked} />;
    return hasFreshStepUp() ? <EnrolForm owner={owner} /> : <StepUpPrompt />;
  }
  return (
    <>
      {unlocked === null ? <UnlockForm owner={owner} ownKey={ownKey.data} /> : <FingerprintCard keys={unlocked} />}
      <ReenrolPanel owner={owner} ownKey={ownKey.data} onOpenKeyRecovery={onOpenKeyRecovery} />
    </>
  );
}

interface KeysScreenProps {
  onBack: () => void;
  onSignOut: () => void;
  /** The employee's key recovery, offered once a new key is active (spec §9.6). */
  onOpenKeyRecovery?: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** Personal keys for opening archives (spec §8.3); recording itself never needs them. */
export function KeysScreen({
  onBack,
  onSignOut,
  onOpenKeyRecovery,
  accountUrl,
  studioUrl,
}: Readonly<KeysScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  useScreenLocale('de');

  return (
    <ScreenShell>
      <AdminHeader
        onBack={onBack}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">{t('admin.keys.title')}</h1>
          <p className="text-note leading-chat text-fg-muted">{t('admin.keys.intro')}</p>
        </div>
        <KeysPanel onOpenKeyRecovery={onOpenKeyRecovery} />
      </div>
    </ScreenShell>
  );
}
