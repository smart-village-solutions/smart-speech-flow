import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { useScreenLocale } from '@/app/providers/locale';
import { useUnlockedKeys } from '@/features/keys/useKeys';
import { StaffViewShell } from '@/features/archive/StaffViewShell';
import { Button } from '@/ui/primitives/Button';
import { ReviewInbox } from './ReviewInbox';
import { ReviewScreen } from './ReviewScreen';
import { INBOX_QUERY } from './useReviews';

interface ReviewsScreenProps {
  onBack: () => void;
  onOpenKeys: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** A reviewer's assignments and the review itself (spec §10.7). */
export function ReviewsScreen({
  onBack,
  onOpenKeys,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<ReviewsScreenProps>) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const unlocked = useUnlockedKeys();
  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState<'decided' | 'declined' | null>(null);
  useScreenLocale('de');
  const viewing = open !== null && unlocked !== null;
  const finish = (outcome: 'decided' | 'declined') => {
    setOpen(null);
    setDone(outcome);
    void queries.invalidateQueries({ queryKey: INBOX_QUERY });
  };

  return (
    <StaffViewShell
      onBack={onBack}
      onClose={viewing ? () => setOpen(null) : undefined}
      onSignOut={onSignOut}
      accountUrl={accountUrl}
      studioUrl={studioUrl}
    >
      {viewing ? (
        <ReviewScreen key={open} verificationId={open} unlocked={unlocked} onDone={finish} />
      ) : (
        <>
          <div className="rounded-2xl border border-border-card bg-surface-card p-5">
            <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">
              {t('admin.review.title')}
            </h1>
            <p className="text-note leading-chat text-fg-muted">{t('admin.review.intro')}</p>
          </div>
          {done !== null && (
            <p
              role="status"
              className="rounded-2xl border border-border-card bg-surface-card p-5 text-note text-fg-status"
            >
              {t(`admin.review.done.${done}`)}
            </p>
          )}
          {unlocked === null ? (
            <div className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
              <p className="text-note text-fg-muted">{t('admin.review.locked')}</p>
              <Button
                variant="compact"
                className="self-start bg-accent text-accent-on"
                onClick={onOpenKeys}
              >
                {t('admin.review.unlock')}
              </Button>
            </div>
          ) : (
            <ReviewInbox
              onOpen={(id) => {
                setDone(null);
                setOpen(id);
              }}
            />
          )}
        </>
      )}
    </StaffViewShell>
  );
}
