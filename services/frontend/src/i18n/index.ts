import i18next, { type i18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import am from './locales/am.json';
import ar from './locales/ar.json';
import de from './locales/de.json';
import en from './locales/en.json';
import fa from './locales/fa.json';
import ku from './locales/ku.json';
import ru from './locales/ru.json';
import ti from './locales/ti.json';
import tr from './locales/tr.json';
import uk from './locales/uk.json';

/**
 * Every language the gateway offers (`api_gateway/session.py:48`) has a
 * catalogue, so a customer never lands on a screen in someone else's language.
 * They are bundled rather than fetched: all ten are 13.6 KB gzipped together,
 * and loading them on demand would leave the UI in the previous language for
 * the length of a round trip.
 */
export const CATALOGUES = { am, ar, de, en, fa, ku, ru, ti, tr, uk } as const;

export const SUPPORTED_UI_LOCALES = Object.keys(CATALOGUES) as UiLocale[];

export type UiLocale = keyof typeof CATALOGUES;

export type TextDirection = 'ltr' | 'rtl';

/**
 * Of the gateway's ten languages only Arabic and Persian are written right to
 * left. Kurdish is served as Kurmancî, which uses the Latin alphabet, and
 * Amharic and Tigrinya use Ge'ez, which runs left to right.
 */
const RTL_LOCALES = new Set(['ar', 'fa']);

export function directionFor(locale: string): TextDirection {
  return RTL_LOCALES.has(locale) ? 'rtl' : 'ltr';
}

export function createI18n(initialLocale: string = 'de'): i18n {
  const instance = i18next.createInstance();

  void instance.use(initReactI18next).init({
    resources: Object.fromEntries(
      Object.entries(CATALOGUES).map(([locale, translation]) => [locale, { translation }])
    ),
    lng: initialLocale,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    returnNull: false,
  });

  return instance;
}
