import { useTranslation } from 'react-i18next';
// The languages query is a hook over a domain repository, not UI. Duplicating
// it in this feature would be worse than importing it across the boundary.
import { useLanguages } from '@/features/language-select/useLanguages';
import type { AdminSession } from '@/domain/admin/admin.types';
import { AdminSessionRow } from './AdminSessionRow';

interface AdminSessionListProps {
  sessions: readonly AdminSession[];
  isError: boolean;
  onEnter: (sessionId: string) => void;
}

export function AdminSessionList({ sessions, isError, onEnter }: Readonly<AdminSessionListProps>) {
  const { t } = useTranslation();
  const { data: languages = [] } = useLanguages();

  // One clock for the whole render, so two rows cannot disagree about now.
  const now = new Date();
  const nameFor = (code: string | null) =>
    languages.find((language) => language.code === code) ?? null;

  let body;
  if (isError) {
    body = <p className="px-5 py-4 text-label text-fg-muted">{t('admin.sessions.loadFailed')}</p>;
  } else if (sessions.length === 0) {
    body = <p className="px-5 py-4 text-label text-fg-muted">{t('admin.sessions.empty')}</p>;
  } else {
    body = sessions.map((session) => (
      <AdminSessionRow
        key={session.id}
        session={session}
        language={nameFor(session.customerLanguage)}
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
