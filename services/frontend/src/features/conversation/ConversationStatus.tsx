import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import type { StatusSnapshot } from './conversation.status';

interface ConversationStatusProps extends StatusSnapshot {
  onRetry?: (() => void) | null;
}

/**
 * A single pill under the header. The export has no error or connection states,
 * so this is new design: bare centred text collided with the first bubble and
 * read as a rendering fault rather than a message.
 *
 * At most one thing is said at a time, most severe first — a finished
 * conversation has no connection left to worry about.
 */
export function ConversationStatus({
  ended,
  connection,
  hasConnected,
  errorKey,
  onRetry = null,
}: ConversationStatusProps) {
  const { t } = useTranslation();

  if (errorKey !== null) {
    return (
      <Pill alert role="alert" icon={<AlertTriangle size={14} strokeWidth={2} />}>
        <span className="truncate">{t(errorKey)}</span>
        {onRetry !== null && (
          <button
            type="button"
            onClick={onRetry}
            className="shrink-0 underline underline-offset-2 hover:text-fg-strong"
          >
            {t('conversation.retry')}
          </button>
        )}
      </Pill>
    );
  }

  if (ended) {
    return (
      <Pill role="status" icon={<CheckCircle2 size={14} strokeWidth={2} />}>
        <span className="truncate">{t('conversation.ended')}</span>
      </Pill>
    );
  }

  if (hasConnected && connection !== 'connected') {
    return (
      <Pill role="status" icon={<PulsingDot />}>
        <span className="truncate">{t('conversation.reconnecting')}</span>
      </Pill>
    );
  }

  return null;
}

interface PillProps {
  children: ReactNode;
  icon: ReactNode;
  role: 'status' | 'alert';
  alert?: boolean;
}

function Pill({ children, icon, role, alert = false }: PillProps) {
  return (
    <div className="absolute inset-x-0 top-header z-10 flex justify-center px-5 pt-2">
      <div
        role={role}
        data-status-pill=""
        className={cn(
          'animate-status-in flex max-w-bubble items-center gap-2 rounded-pill border',
          'bg-surface-status px-3 py-1.5 text-note shadow-lg',
          alert
            ? 'border-border-status-alert text-fg-status-alert'
            : 'border-border-status text-fg-status'
        )}
      >
        <span className="flex shrink-0 items-center">{icon}</span>
        <div className="flex min-w-0 items-center gap-2">{children}</div>
      </div>
    </div>
  );
}

/** The connection is being worked on, so the dot breathes rather than sits. */
function PulsingDot() {
  return <span className="size-2 rounded-full bg-current opacity-70 motion-safe:animate-pulse" />;
}
