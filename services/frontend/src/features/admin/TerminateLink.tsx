import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';
import { ADMIN_SESSIONS_KEY } from './useAdminSessions';

interface TerminateLinkProps {
  sessionId: string;
  onTerminated: () => void;
}

/**
 * A text link rather than a button, matching the export: ending the
 * conversation is deliberate but not the primary action on the screen, and a
 * red button beside the microphone invites the wrong tap.
 */
export function TerminateLink({ sessionId, onTerminated }: Readonly<TerminateLinkProps>) {
  const { t } = useTranslation();
  const { admin } = useServices();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const terminate = useMutation({
    mutationFn: () => admin.terminateSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ADMIN_SESSIONS_KEY });
      setConfirming(false);
      onTerminated();
    },
  });

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-label text-fg-link underline underline-offset-2 transition-colors duration-150 hover:text-fg-link-hover"
      >
        {t('admin.session.terminate')}
      </button>

      <ConfirmDialog
        open={confirming}
        title={t('admin.session.terminateConfirm.title')}
        body={t('admin.session.terminateConfirm.body', { id: sessionId })}
        confirmLabel={t('admin.session.terminateConfirm.confirm')}
        cancelLabel={t('admin.session.terminateConfirm.cancel')}
        error={terminate.isError ? t('admin.session.terminateFailed') : null}
        onConfirm={() => terminate.mutate()}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
