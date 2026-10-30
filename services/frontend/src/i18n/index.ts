import i18next, { type i18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import am from './locales/am.json';
import ar from './locales/ar.json';
import bg from './locales/bg.json';
import de from './locales/de.json';
import el from './locales/el.json';
import en from './locales/en.json';
import es from './locales/es.json';
import fa from './locales/fa.json';
import fr from './locales/fr.json';
import hi from './locales/hi.json';
import hu from './locales/hu.json';
import it from './locales/it.json';
import pl from './locales/pl.json';
import pt from './locales/pt.json';
import ro from './locales/ro.json';
import ru from './locales/ru.json';
import sq from './locales/sq.json';
import tr from './locales/tr.json';
import uk from './locales/uk.json';
import zh from './locales/zh.json';

/**
 * Every language the gateway offers (`SUPPORTED_LANGUAGES` in
 * `api_gateway/message_models.py`) has a catalogue, so a customer never lands
 * on a screen in someone else's language.
 * They are bundled rather than fetched: loading them on demand would leave the
 * UI in the previous language for the length of a round trip.
 */
export const CATALOGUES = {
  am,
  ar,
  bg,
  de,
  el,
  en,
  es,
  fa,
  fr,
  hi,
  hu,
  it,
  pl,
  pt,
  ro,
  ru,
  sq,
  tr,
  uk,
  zh,
} as const;

export const SUPPORTED_UI_LOCALES = Object.keys(CATALOGUES) as UiLocale[];

export type UiLocale = keyof typeof CATALOGUES;

export type TextDirection = 'ltr' | 'rtl';

/**
 * Of the gateway's languages only Arabic and Persian are written right to
 * left. Amharic uses Ge'ez, which runs left to right.
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
