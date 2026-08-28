import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { describeStart, durationMinutes } from '@/lib/sessionTimes';
import { isReenterable } from '@/domain/admin/admin.types';
import type { AdminSession } from '@/domain/admin/admin.types';
import type { Language } from '@/domain/language/language.types';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';

const STATUS_COLOUR = {
  connected: 'text-status-ok',
  open: 'text-status-warn',
  completed: 'text-fg-muted',
} as const;

const ROW =
  'grid w-full grid-cols-4 items-center border-t border-border-divider px-5 py-3 text-start';

interface AdminSessionRowProps {
  session: AdminSession;
  /** Null when the customer never chose one, or when the code is unknown to us. */
  language: Language | null;
  /** Injected so the duration of an open session is testable. */
  now: Date;
  onEnter: (sessionId: string) => void;
}

export function AdminSessionRow({
  session,
  language,
  now,
  onEnter,
}: Readonly<AdminSessionRowProps>) {
  const { t, i18n } = useTranslation();

  const start = describeStart(session.createdAt, now, i18n.language);
  const started =
    start.day === 'other'
      ? t('admin.sessions.on', { day: start.label, time: start.time })
      : t(`admin.sessions.${start.day}`, { time: start.time });
  const minutes = durationMinutes(session.createdAt, session.terminatedAt ?? now.toISOString());

  const cells = (
    <>
      <span className="flex min-w-0 items-center gap-2.5">
        {language === null ? null : <FlagAvatar language={language} size="xs" />}
        <span className="truncate text-note font-medium text-fg-strong">
          {language?.native ?? t('admin.sessions.unknownLanguage')}
        </span>
      </span>
      <span className="truncate text-label text-fg-muted">{started}</span>
      <span className="text-label text-fg-muted">
        {t('admin.sessions.minutes', { count: minutes })}
      </span>
      <span className={cn('text-meta font-medium', STATUS_COLOUR[session.status])}>
        {t(`admin.sessions.status.${session.status}`)}
      </span>
    </>
  );

  // A completed session has nothing to open, so it is a div rather than a
  // disabled button: the export's own switch, and the semantic element
  // SonarCloud asks for over an ARIA role.
  if (!isReenterable(session)) {
    return <div className={cn(ROW, 'opacity-50')}>{cells}</div>;
  }

  return (
    <button
      type="button"
      onClick={() => onEnter(session.id)}
      aria-label={t('admin.sessions.reenter', { id: session.id })}
      className={cn(
        ROW,
        'transition-colors duration-100 hover:bg-surface-row-hover active:bg-surface-row-active'
      )}
    >
      {cells}
    </button>
  );
}
