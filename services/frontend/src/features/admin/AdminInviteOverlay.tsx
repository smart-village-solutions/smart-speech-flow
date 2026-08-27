import { useEffect } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import { CodeDisplay } from '@/ui/patterns/CodeDisplay';
import type { CreatedSession } from '@/domain/admin/admin.types';
import { InviteShareRow } from './InviteShareRow';
import { useJoinWatch } from './useJoinWatch';

interface AdminInviteOverlayProps {
  /** Null until a session has been created; the overlay is then closed. */
  session: CreatedSession | null;
  onEnter: (sessionId: string) => void;
  onCancel: () => void;
}

/**
 * Opaque rather than a scrim: the code is read out across a counter and nothing
 * behind it should compete. Its own component rather than a branch inside the
 * dashboard, where the export keeps both in one 254-line function.
 */
export function AdminInviteOverlay({
  session,
  onEnter,
  onCancel,
}: Readonly<AdminInviteOverlayProps>) {
  const { t } = useTranslation();
  const joined = useJoinWatch(session?.id ?? null);

  useEffect(() => {
    if (joined && session !== null) {
      onEnter(session.id);
    }
  }, [joined, session, onEnter]);

  const code = session?.id ?? '';

  return (
    <Dialog.Root
      open={session !== null}
      onOpenChange={(next) => {
        if (!next) {
          onCancel();
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-surface-page" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-0 z-50 flex flex-col items-center justify-center px-6"
        >
          <div className="flex w-full max-w-invite flex-col gap-6">
            <div className="flex flex-col items-center gap-1.5 text-center">
              <Dialog.Title className="text-overlay-title font-bold text-fg-strong">
                {t('admin.invite.title')}
              </Dialog.Title>
              <p className="text-note text-fg-muted">{t('admin.invite.subtitle')}</p>
            </div>

            <CodeDisplay code={code} label={t('admin.invite.codeLabel', { code })} />

            <InviteShareRow url={session?.clientUrl ?? ''} />

            <button
              type="button"
              onClick={() => {
                if (session !== null) {
                  onEnter(session.id);
                }
              }}
              aria-label={t('admin.invite.enterNow')}
              className="flex w-full items-center gap-3 rounded-2xl border border-border-card bg-surface-card p-4 text-start"
            >
              <span aria-hidden className="relative flex size-3 shrink-0">
                <span className="absolute inline-flex size-full animate-ping rounded-pill bg-accent opacity-60" />
                <span className="relative inline-flex size-3 rounded-pill bg-accent" />
              </span>
              <span className="text-label leading-snug text-fg-muted">
                {t('admin.invite.waiting')}
              </span>
            </button>

            <Button
              variant="sheet"
              onClick={onCancel}
              className="border border-border-card text-fg-link"
            >
              {t('admin.invite.cancel')}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
