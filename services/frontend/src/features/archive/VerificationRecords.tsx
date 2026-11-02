import { useTranslation } from 'react-i18next';
import { recordMeta } from './recordMeta';
import type { RecordView } from './verifyRecords';

interface VerificationRecordsProps {
  records: readonly RecordView[];
  /** Absent for whoever may not assign; offered on a declined or withdrawn row. */
  onReassign?: () => void;
}

const ALERT = new Set(['not_approved', 'broken']);
const QUIET = new Set(['declined', 'withdrawn']);

function chipTone(status: string): string {
  if (ALERT.has(status)) return 'text-fg-status-alert';
  return QUIET.has(status) ? 'text-fg-muted' : 'text-fg-status';
}

function Chip({ label, tone }: Readonly<{ label: string; tone: string }>) {
  return (
    <span className={`rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium ${tone}`}>
      {label}
    </span>
  );
}

function RecordRow({ view, onReassign }: Readonly<{ view: RecordView; onReassign?: () => void }>) {
  const { t, i18n } = useTranslation();
  const { record } = view;
  const sworn = record.permissionSnapshot?.includes('ssf.recording.review.sworn') === true;
  const reassignable = view.state === 'closed' && onReassign !== undefined;
  return (
    <li className="flex flex-col gap-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-note font-semibold text-fg-strong">
          {record.reviewerName ?? record.reviewerSub}
        </span>
        {sworn && <Chip label={t('admin.archive.verification.sworn')} tone="text-fg-status" />}
        {view.state !== 'broken' && (
          <Chip
            label={t(`admin.archive.verification.state.${record.status}`)}
            tone={chipTone(record.status)}
          />
        )}
      </div>
      {view.state === 'broken' ? (
        <p role="alert" className="text-label text-fg-status-alert">
          {t('admin.archive.verification.broken')}
        </p>
      ) : (
        <p className="text-label text-fg-muted">{recordMeta(t, view, i18n.language)}</p>
      )}
      {view.overall && (
        <p className="whitespace-pre-wrap border-s-2 border-border-divider ps-3 text-note text-fg-body">
          {view.overall}
        </p>
      )}
      {reassignable && (
        <button
          type="button"
          onClick={onReassign}
          className="self-start text-label font-medium text-fg-link"
        >
          {t('admin.archive.verification.reassign')}
        </button>
      )}
    </li>
  );
}

/** Every record of the conversation; content only for decided ones that checked out. */
export function VerificationRecords({ records, onReassign }: Readonly<VerificationRecordsProps>) {
  const { t } = useTranslation();
  if (records.length === 0) return null;
  return (
    <section className="rounded-2xl border border-border-card bg-surface-card">
      <h3 className="px-4 pt-3 text-note font-semibold text-fg-strong">
        {t('admin.archive.verification.records')}
      </h3>
      <ul className="divide-y divide-border-divider">
        {records.map((view) => (
          <RecordRow key={view.record.verificationId} view={view} onReassign={onReassign} />
        ))}
      </ul>
    </section>
  );
}
