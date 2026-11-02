import type { TFunction } from 'i18next';
import { formatTime } from './format';
import type { RecordView } from './verifyRecords';

/** One line of what a record's reader may know about it, parts joined by a middle dot. */
export function recordMeta(t: TFunction, view: Readonly<RecordView>, locale: string): string {
  const { record } = view;
  const at = (value: string) => formatTime(value, locale);
  const parts = [t('admin.archive.verification.requested', { time: at(record.requestedAt) })];
  if (record.decidedAt !== null)
    parts.push(t('admin.archive.verification.decided', { time: at(record.decidedAt) }));
  if (record.closeReason !== null)
    parts.push(t(`admin.archive.verification.closeReason.${record.closeReason}`));
  if (view.entriesAfter > 0)
    parts.push(t('admin.archive.verification.olderHead', { count: view.entriesAfter }));
  if (view.stampTime !== null) {
    parts.push(
      `${t('admin.archive.verification.stampAt', { time: at(view.stampTime) })} ${t('admin.archive.stamp.unverified')}`
    );
  }
  if (view.missingKeys) parts.push(t('admin.archive.verification.missingKeyNotes'));
  return parts.join(' · ');
}
