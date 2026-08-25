/**
 * A language is not a country, so several of these are conventions rather than
 * facts: Arabic uses Saudi Arabia, Amharic uses Ethiopia, Tigrinya uses Eritrea,
 * English uses the United Kingdom. Kurdish is deliberately absent — it has no
 * ISO 3166 country code, and picking one would be a political statement. It
 * falls back to a neutral text chip. See docs/frontend/API_GAPS.md.
 */
export const LANGUAGE_FLAG_CODES: Record<string, string> = {
  en: 'gb',
  ar: 'sa',
  tr: 'tr',
  ru: 'ru',
  uk: 'ua',
  am: 'et',
  ti: 'er',
  fa: 'ir',
};

export function flagCodeFor(languageCode: string): string | null {
  return LANGUAGE_FLAG_CODES[languageCode] ?? null;
}
