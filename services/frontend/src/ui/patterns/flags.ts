/**
 * A language is not a country, so several of these are conventions rather than
 * facts: Arabic uses Saudi Arabia, Amharic uses Ethiopia,
 * English uses the United Kingdom, Portuguese uses Portugal, Chinese uses China
 * and Hindi uses India. Unknown languages fall back to a neutral text chip.
 * See docs/frontend/API_GAPS.md.
 */
const LANGUAGE_FLAG_CODES: Record<string, string> = {
  en: 'gb',
  ar: 'sa',
  tr: 'tr',
  ru: 'ru',
  uk: 'ua',
  am: 'et',
  fa: 'ir',
  it: 'it',
  ro: 'ro',
  pl: 'pl',
  bg: 'bg',
  el: 'gr',
  fr: 'fr',
  es: 'es',
  pt: 'pt',
  sq: 'al',
  hu: 'hu',
  zh: 'cn',
  hi: 'in',
};

export function flagCodeFor(languageCode: string): string | null {
  return LANGUAGE_FLAG_CODES[languageCode] ?? null;
}
