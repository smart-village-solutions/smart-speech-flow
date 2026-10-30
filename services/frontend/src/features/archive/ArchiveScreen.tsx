import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import type { OwnConversation } from '@/domain/archive/archive.types';
import { KeyRecoveryBanner } from '@/features/recovery/KeyRecoveryBanner';
import { ArchiveList } from './ArchiveList';
import { ConversationViewer } from './ConversationViewer';

interface ArchiveScreenProps {
  onBack: () => void;
  onOpenKeys: () => void;
  /** Offered when the employee's key cannot open some conversations (spec §9.6). */
  onOpenKeyRecovery?: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

function LockedNotice({ onOpenKeys }: Readonly<{ onOpenKeys: () => void }>) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
      <p className="text-note text-fg-muted">{t('admin.archive.locked')}</p>
      <Button
        variant="compact"
        className="self-start bg-accent text-accent-on"
        onClick={onOpenKeys}
      >
        {t('admin.archive.unlock')}
      </Button>
    </div>
  );
}

/** The employee's own recorded conversations (spec §10.6). */
export function ArchiveScreen({
  onBack,
  onOpenKeys,
  onOpenKeyRecovery,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<ArchiveScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const unlocked = useUnlockedKeys();
  const [open, setOpen] = useState<OwnConversation | null>(null);
  useScreenLocale('de');
  const viewing = open !== null && unlocked !== null;

  return (
    <ScreenShell>
      <AdminHeader
        onBack={viewing ? () => setOpen(null) : onBack}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        {viewing ? (
          <ConversationViewer
            key={open.conversationId}
            conversationId={open.conversationId}
            employeeSub={open.employeeSub}
            unlocked={unlocked}
          />
        ) : (
          <>
            <div className="rounded-2xl border border-border-card bg-surface-card p-5">
              <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">
                {t('admin.archive.title')}
              </h1>
              <p className="text-note leading-chat text-fg-muted">{t('admin.archive.intro')}</p>
            </div>
            {unlocked === null ? (
              <LockedNotice onOpenKeys={onOpenKeys} />
            ) : (
              <>
                {onOpenKeyRecovery && <KeyRecoveryBanner onOpen={onOpenKeyRecovery} />}
                <ArchiveList onOpen={setOpen} />
              </>
            )}
          </>
        )}
      </div>
    </ScreenShell>
  );
}
