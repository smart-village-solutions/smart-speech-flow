import { useTranslation } from 'react-i18next';
import type { RecordView } from './verifyRecords';

interface FindingsColumnsProps {
  entryId: string;
  records: readonly RecordView[];
}

/** Every decided reviewer's findings on one entry, side by side (spec §10.7). */
export function FindingsColumns({ entryId, records }: Readonly<FindingsColumnsProps>) {
  const { t } = useTranslation();
  const columns = records.filter((view) => view.state === 'verified' && view.findings.has(entryId));
  if (columns.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-3">
      {columns.map((view) => (
        <section
          key={view.record.verificationId}
          className="flex min-w-findings-column flex-1 flex-col gap-2"
        >
          <h4 className="text-meta font-semibold text-fg-muted">
            {view.record.reviewerName ?? view.record.reviewerSub} ·{' '}
            {t(`admin.archive.verification.state.${view.record.status}`)}
          </h4>
          {(view.findings.get(entryId) ?? []).map((finding) => (
            <div key={finding.key} className="text-label">
              <p className="font-medium text-fg-strong">
                {t(`admin.archive.verification.category.${finding.category}`)}
              </p>
              <p className="whitespace-pre-wrap text-fg-body">{finding.text}</p>
              {finding.suggestion !== '' && (
                <p className="whitespace-pre-wrap text-fg-muted">
                  {t('admin.archive.verification.suggestion')} {finding.suggestion}
                </p>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
