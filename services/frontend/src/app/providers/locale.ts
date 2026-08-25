import { createContext, useContext, useEffect } from 'react';
import { SUPPORTED_UI_LOCALES } from '@/i18n';

export interface LocaleContextValue {
  locale: string;
  setLocale: (locale: string) => void;
}

export const LocaleContext = createContext<LocaleContextValue | null>(null);

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);

  if (value === null) {
    throw new Error('useLocale must be used inside a LocaleProvider');
  }

  return value;
}

/**
 * States the language a screen is shown in. The access-code screen is German
 * and the language picker is English, because neither knows the customer yet;
 * everything after the choice follows the customer. Passing an empty string
 * declares nothing, which is what the conversation screen does until its
 * session has loaded.
 */
export function useScreenLocale(locale: string): void {
  const { setLocale } = useLocale();

  useEffect(() => {
    if (locale !== '') {
      setLocale(locale);
    }
  }, [locale, setLocale]);
}

export function isSupportedLocale(locale: string): boolean {
  return (SUPPORTED_UI_LOCALES as string[]).includes(locale);
}
