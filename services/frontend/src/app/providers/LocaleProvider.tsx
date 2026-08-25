import { useCallback, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { isSupportedLocale, LocaleContext } from './locale';

interface LocaleProviderProps {
  children: ReactNode;
  /** German until the customer has chosen; see `useScreenLocale`. */
  initialLocale?: string;
}

export function LocaleProvider({ children, initialLocale = 'de' }: LocaleProviderProps) {
  const [locale, setLocaleState] = useState(initialLocale);

  // A language the gateway offers but the UI has no catalogue for would render
  // as English via the i18next fallback. Holding the previous locale instead
  // keeps the screen in one language rather than half in two.
  const setLocale = useCallback((next: string) => {
    setLocaleState((current) => (isSupportedLocale(next) ? next : current));
  }, []);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
