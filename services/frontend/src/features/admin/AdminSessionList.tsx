import { useTranslation } from 'react-i18next';
import type { AdminSession } from '@/domain/admin/admin.types';
import { AdminSessionRow } from './AdminSessionRow';
import { useStaffLocalisation } from './useStaffLocalisation';
import { EmptyState } from '@/ui/patterns/EmptyState';
import { InlineAlert } from '@/ui/patterns/InlineAlert';

interface AdminSessionListProps {
  sessions: readonly AdminSession[];
  isError: boolean;
  onEnter: (sessionId: string) => void;
}

export function AdminSessionList({ sessions, isError, onEnter }: Readonly<AdminSessionListProps>) {
  const { t } = useTranslation();
  const { languageOf, timeZone } = useStaffLocalisation();

  // One clock for the whole render, so two rows cannot disagree about now.
  const now = new Date();

  let body;
  if (isError) {
    body = <InlineAlert tone="danger" title={t('admin.sessions.loadFailed')} className="rounded-none border-0 px-5" />;
  } else if (sessions.length === 0) {
    body = <EmptyState title={t('admin.sessions.empty')} className="rounded-none border-0" />;
  } else {
    body = sessions.map((session) => (
      <AdminSessionRow
        key={session.id}
        session={session}
        language={languageOf(session.customerLanguage)}
        timeZone={timeZone}
        now={now}
        onEnter={onEnter}
      />
    ));
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border-card bg-surface-card">
      <p className="px-5 pb-3 pt-5 text-caption font-semibold uppercase tracking-widest text-fg-muted">
        {t('admin.sessions.title')}
      </p>
      {body}
    </div>
  );
}
