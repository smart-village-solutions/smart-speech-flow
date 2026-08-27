import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';
import type { CreatedSession } from '@/domain/admin/admin.types';
import { AdminInviteOverlay } from './AdminInviteOverlay';
import { ADMIN_SESSIONS_KEY } from './useAdminSessions';

interface AdminNewSessionButtonProps {
  /** The one session that would be terminated by creating another, if any. */
  liveSessionId: string | null;
  onEnter: (sessionId: string) => void;
}

/**
 * The create flow: warn, create, invite, resolve. Separate from the dashboard
 * because it carries two pieces of state and two dialogs, and the dashboard is
 * a composer.
 *
 * Cancelling the invite terminates the session it created, so a code that was
 * read aloud stops working rather than staying joinable behind a closed overlay.
 */
export function AdminNewSessionButton({
  liveSessionId,
  onEnter,
}: Readonly<AdminNewSessionButtonProps>) {
  const { t } = useTranslation();
  const { admin } = useServices();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [invite, setInvite] = useState<CreatedSession | null>(null);

  const create = useMutation({
    mutationFn: () => admin.createSession(),
    onSuccess: (created) => {
      setInvite(created);
      // The gateway terminated whatever was live, so the list is now stale.
      void queryClient.invalidateQueries({ queryKey: ADMIN_SESSIONS_KEY });
    },
  });

  const start = () => {
    setConfirming(false);
    create.mutate();
  };

  /**
   * The overlay closes at once and the session is ended behind it: blocking a
   * dismissal on a round trip is worse than an optimistic one. A terminate that
   * fails leaves the row in the list as still open, which is the honest report —
   * so the list is refreshed either way rather than the error being swallowed
   * silently.
   */
  const cancelInvite = () => {
    const pending = invite;
    setInvite(null);

    if (pending === null) {
      return;
    }

    void admin
      .terminateSession(pending.id)
      .catch(() => undefined)
      .finally(() => queryClient.invalidateQueries({ queryKey: ADMIN_SESSIONS_KEY }));
  };

  const press = () => {
    if (liveSessionId === null) {
      start();
      return;
    }
    setConfirming(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={press}
        disabled={create.isPending}
        className="w-full rounded-2xl bg-accent py-4 text-item font-semibold text-accent-on shadow-lg active:scale-[0.98] disabled:opacity-40"
      >
        {t('admin.dashboard.newSession')}
      </button>

      {create.isError && (
        <p role="alert" className="text-label text-fg-status-alert">
          {t('admin.invite.createFailed')}
        </p>
      )}

      <ConfirmDialog
        open={confirming}
        title={t('admin.confirm.title')}
        body={t('admin.confirm.body', { id: liveSessionId ?? '' })}
        confirmLabel={t('admin.confirm.confirm')}
        cancelLabel={t('admin.confirm.cancel')}
        onConfirm={start}
        onCancel={() => setConfirming(false)}
      />

      <AdminInviteOverlay session={invite} onEnter={onEnter} onCancel={cancelInvite} />
    </>
  );
}
