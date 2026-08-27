import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { isSupportedLocale, LocaleContext } from './locale';

interface LocaleProviderProps {
  children: ReactNode;
  /** German until the customer has chosen; see `useScreenLocale`. */
  initialLocale?: string;
}

export function LocaleProvider({ children, initialLocale = 'de' }: Readonly<LocaleProviderProps>) {
  const [locale, setLocale] = useState(initialLocale);

  // Shadows the state for readers that run outside render; see `getLocale`.
  const currentRef = useRef(initialLocale);

  useEffect(() => {
    currentRef.current = locale;
  }, [locale]);

  // A language the gateway offers but the UI has no catalogue for would render
  // as English via the i18next fallback. Holding the previous locale instead
  // keeps the screen in one language rather than half in two.
  const selectLocale = useCallback((next: string) => {
    setLocale((current) => (isSupportedLocale(next) ? next : current));
  }, []);

  const getLocale = useCallback(() => currentRef.current, []);

  const value = useMemo(
    () => ({ locale, setLocale: selectLocale, getLocale }),
    [locale, selectLocale, getLocale]
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
