import { useEffect, useMemo } from 'react';
import type { ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { createI18n, directionFor } from '@/i18n';

interface I18nProviderProps {
  children: ReactNode;
  /** Follows the language the customer chose; defaults to German. */
  locale?: string;
}

export function I18nProvider({ children, locale = 'de' }: I18nProviderProps) {
  // Created once; the locale is switched through the effect below rather than
  // by rebuilding the instance.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const instance = useMemo(() => createI18n(locale), []);

  useEffect(() => {
    if (instance.language !== locale) {
      void instance.changeLanguage(locale);
    }
  }, [instance, locale]);

  // The root element carries the language for assistive technology and the
  // writing direction for the layout, which is what makes `ms-`/`me-` spacing
  // and `text-start` mirror for Arabic and Persian.
  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = directionFor(locale);
  }, [locale]);

  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}
