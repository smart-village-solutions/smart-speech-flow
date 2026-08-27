import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import type { RealtimeStatus } from '@/core/realtime/realtime.port';
import type { Language } from '@/domain/language/language.types';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';

type Connection = 'connected' | 'connecting' | 'interrupted';

const LAMP: Record<Connection, string> = {
  connected: 'bg-status-ok',
  connecting: 'bg-status-warn',
  interrupted: 'bg-status-down',
};

/**
 * The gateway emits no connection events, so this is the transport's own view.
 * `disconnected` is the state a socket is in before its first open, which reads
 * as connecting rather than as something lost.
 */
function connectionOf(status: RealtimeStatus): Connection {
  if (status === 'connected') {
    return 'connected';
  }
  if (status === 'error') {
    return 'interrupted';
  }
  return 'connecting';
}

interface SessionStatusOverlayProps {
  sessionId: string;
  connection: RealtimeStatus;
  /** Null until the customer has chosen one; the group is then omitted. */
  language: Language | null;
}

/**
 * Floats between the header and the chat. `role="status"`, unlike the dev
 * banner: this text changes while the admin is reading the screen, which is
 * exactly what a live region is for.
 */
export function SessionStatusOverlay({
  sessionId,
  connection,
  language,
}: Readonly<SessionStatusOverlayProps>) {
  const { t } = useTranslation();
  const state = connectionOf(connection);

  return (
    <div
      className="pointer-events-none fixed inset-x-0 z-10 flex justify-center px-5"
      style={{ top: 'var(--spacing-status-top)' }}
    >
      <div
        role="status"
        className={cn(
          'pointer-events-auto flex items-center gap-3 rounded-pill border px-4 py-2',
          'border-border-status bg-surface-status/90 shadow-lg backdrop-blur-sm'
        )}
      >
        <span className="font-mono text-caption font-medium text-fg-muted">{sessionId}</span>

        <span aria-hidden className="h-3 w-px bg-border-status" />

        <span className="flex items-center gap-1.5">
          <span aria-hidden className="relative flex size-2 shrink-0">
            {state === 'connecting' && (
              <span
                className={cn(
                  'absolute inline-flex size-full animate-ping rounded-pill opacity-75',
                  LAMP[state]
                )}
              />
            )}
            <span className={cn('relative inline-flex size-2 rounded-pill', LAMP[state])} />
          </span>
          <span className="text-meta font-medium text-fg-status">
            {t(`admin.session.connection.${state}`)}
          </span>
        </span>

        {language !== null && (
          <>
            <span aria-hidden className="h-3 w-px bg-border-status" />
            <span className="flex items-center gap-1.5">
              <FlagAvatar language={language} size="2xs" />
              <span className="text-meta text-fg-muted">{language.native}</span>
            </span>
          </>
        )}
      </div>
    </div>
  );
}
