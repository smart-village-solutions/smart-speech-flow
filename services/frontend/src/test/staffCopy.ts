import { createI18n } from '@/i18n';
import { staffCopy, type StaffCopy } from '@/features/content/staffCopy';

/** What the dashboard hands its children without Studio content. */
export function bundledStaffCopy(): StaffCopy {
  return staffCopy(undefined, 'de', createI18n('de').t, 'kassel');
}
