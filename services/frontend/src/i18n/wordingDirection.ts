/** Known horizontal script directions for browsers without locale text-info APIs. */
const RTL_SCRIPTS = new Set([
  'Adlm',
  'Arab',
  'Hebr',
  'Mand',
  'Nkoo',
  'Rohg',
  'Samr',
  'Syrc',
  'Thaa',
  'Yezi',
]);
const LTR_SCRIPTS = new Set([
  'Armn',
  'Beng',
  'Bopo',
  'Cans',
  'Cher',
  'Cyrl',
  'Deva',
  'Ethi',
  'Geor',
  'Grek',
  'Gujr',
  'Guru',
  'Hang',
  'Hani',
  'Hans',
  'Hant',
  'Jpan',
  'Khmr',
  'Knda',
  'Kore',
  'Laoo',
  'Latn',
  'Mlym',
  'Mong',
  'Mymr',
  'Orya',
  'Sinh',
  'Taml',
  'Telu',
  'Thai',
  'Tibt',
  'Yiii',
]);

/** Source wording can use locales and explicit scripts outside the UI catalogues. */
export function wordingDirectionFor(tag: string): 'ltr' | 'rtl' | 'auto' {
  try {
    const locale = new Intl.Locale(tag);
    // `und` has no known language; likely-subtag expansion must not guess English.
    if (!locale.script && (!locale.language || locale.language === 'und')) return 'auto';
    // Explicit script wins over the language's likely script (for example ar-Latn).
    const script = locale.script ?? locale.maximize?.().script;
    if (script && RTL_SCRIPTS.has(script)) return 'rtl';
    if (script && LTR_SCRIPTS.has(script)) return 'ltr';
  } catch {
    // Invalid tags and browsers without locale metadata use first-strong direction.
  }
  return 'auto';
}
