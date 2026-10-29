import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';
import { formatDate, formatTime } from './format';
import type { AmendmentView } from './timeline';

interface AmendmentNoteProps {
  amendment: AmendmentView;
  /** Amending an amendment is how it is corrected: both stay (concept §10.1). */
  /** Absent while an earlier amendment waits for confirmation. */
  onAmend?: (entryId: string) => void;
}

export function AmendmentNote({ amendment, onAmend }: Readonly<AmendmentNoteProps>) {
  const { t, i18n } = useTranslation();
  const at = amendment.createdAt;
  const time = `${formatDate(at, i18n.language)} ${formatTime(at, i18n.language)}`;
  return (
    <div className="flex flex-col gap-1 border-s-2 border-border-status ps-3">
      <p className="text-meta font-medium text-fg-muted">
        {t('admin.archive.amendment.label', { time })}
        {amendment.superseded && ` ${t('admin.archive.amendment.superseded')}`}
        {amendment.foreignAuthor && ` ${t('admin.archive.amendment.foreignAuthor')}`}
      </p>
      <p className="whitespace-pre-wrap text-note text-fg-body">{amendment.record.text}</p>
      {onAmend && (
        <Button variant="compact" className="self-start" onClick={() => onAmend(amendment.entryId)}>
          {t('admin.archive.amend')}
        </Button>
      )}
    </div>
  );
}
