import type { TFunction } from 'i18next';
import type { VerificationSummary } from '@/domain/archive/archive.types';
import type { RecordView } from './verifyRecords';

/** The derived summary of spec §10.5, as one label. */
export function summaryLabel(t: TFunction, summary: Readonly<VerificationSummary>): string {
  return t(`admin.archive.verification.status.${summary.status}`, {
    approved: summary.approved,
    notApproved: summary.notApproved,
  });
}

/** What the viewer can vouch for: outcomes only of records that passed their check. */
export function verifiedSummary(records: readonly RecordView[]): VerificationSummary {
  const outcomes = records.filter((view) => view.state === 'verified');
  const approved = outcomes.filter((view) => view.record.decided?.outcome === 'approved').length;
  const notApproved = outcomes.length - approved;
  let status: VerificationSummary['status'] = 'not_verified';
  if (records.some((view) => view.state === 'open')) status = 'in_review';
  else if (outcomes.length > 0) status = 'decided';
  return { status, approved, notApproved };
}
