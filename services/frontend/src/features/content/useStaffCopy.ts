import { useTranslation } from 'react-i18next';
import { useBrand } from '@/app/providers/brand';
import { useLocale } from '@/app/providers/locale';
import { staffCopy, type StaffCopy } from './staffCopy';
import { useStaffContent } from './useStaffContent';

export function useStaffCopy(): StaffCopy {
  const { content } = useStaffContent();
  const { locale } = useLocale();
  const { t } = useTranslation();
  const { brand } = useBrand();
  return staffCopy(content, locale, t, brand);
}
