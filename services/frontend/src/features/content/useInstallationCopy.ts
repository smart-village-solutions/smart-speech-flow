import { useTranslation } from 'react-i18next';
import { useLocale } from '@/app/providers/locale';
import { loginCopy, startpageCopy, type LoginCopy, type StartpageCopy } from './installationCopy';
import { usePublicContent } from './usePublicContent';

export function useStartpageCopy(): StartpageCopy {
  const { content } = usePublicContent();
  const { locale } = useLocale();
  const { t } = useTranslation();
  return startpageCopy(content, locale, t);
}

export function useLoginCopy(): LoginCopy {
  const { content } = usePublicContent();
  const { locale } = useLocale();
  const { t } = useTranslation();
  return loginCopy(content, locale, t);
}
