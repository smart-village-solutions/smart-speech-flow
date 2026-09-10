import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ThemeContext, type Theme } from './theme';

interface ThemeProviderProps {
  children: ReactNode;
  /** Lets tests render a deterministic theme without reading browser settings. */
  initialTheme?: Theme;
}

const THEME_STORAGE_KEY = 'ssf-theme';
const COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)';

function savedTheme(): Theme | null {
  try {
    const theme = window.localStorage.getItem(THEME_STORAGE_KEY);
    return theme === 'dark' || theme === 'light' ? theme : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia(COLOR_SCHEME_QUERY).matches ? 'dark' : 'light';
}

export function ThemeProvider({ children, initialTheme }: Readonly<ThemeProviderProps>) {
  const [persistedTheme] = useState<Theme | null>(savedTheme);
  const [hasManualTheme, setHasManualTheme] = useState(() => persistedTheme !== null);
  const [theme, setTheme] = useState<Theme>(() => initialTheme ?? persistedTheme ?? systemTheme());

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    if (initialTheme !== undefined || hasManualTheme) {
      return;
    }

    const mediaQuery = window.matchMedia(COLOR_SCHEME_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setTheme(event.matches ? 'dark' : 'light');
    };
    mediaQuery.addEventListener('change', onChange);
    return () => mediaQuery.removeEventListener('change', onChange);
  }, [hasManualTheme, initialTheme]);

  const toggleTheme = useCallback(() => {
    setHasManualTheme(true);
    setTheme((current) => {
      const nextTheme = current === 'dark' ? 'light' : 'dark';
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
      } catch {
        // The selected theme remains active for this page even when storage is unavailable.
      }
      return nextTheme;
    });
  }, []);

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
