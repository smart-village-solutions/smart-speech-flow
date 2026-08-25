import { describe, expect, it } from 'vitest';
import de from '@/i18n/locales/de.json';
import en from '@/i18n/locales/en.json';
import { CATALOGUES, createI18n, SUPPORTED_UI_LOCALES } from '@/i18n';

function flatten(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof entry === 'object' && entry !== null
      ? flatten(entry as Record<string, unknown>, path)
      : [path];
  });
}

function read(catalogue: Record<string, unknown>, key: string): unknown {
  return key
    .split('.')
    .reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], catalogue);
}

/** Explicit, because the default sort compares by UTF-16 code unit. */
const byName = (a: string, b: string) => a.localeCompare(b);

describe('translation catalogues', () => {
  const reference = flatten(de).sort(byName);

  it('covers every language the gateway offers', () => {
    expect([...SUPPORTED_UI_LOCALES].sort(byName)).toEqual(
      ['am', 'ar', 'de', 'en', 'fa', 'ku', 'ru', 'ti', 'tr', 'uk'].sort(byName)
    );
  });

  it('ships a catalogue for every supported locale', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      expect(CATALOGUES[locale], locale).toBeDefined();
    }
  });

  it('define exactly the same keys', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      expect(flatten(CATALOGUES[locale]).sort(byName), locale).toEqual(reference);
    }
  });

  it('have no empty strings', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      for (const key of reference) {
        expect(read(CATALOGUES[locale], key), `${locale}.${key}`).not.toBe('');
      }
    }
  });

  // A copied catalogue is worse than a missing one: it reads as translated and
  // is not. German is exempt because it is the source.
  it('translate the screens rather than copying the German source', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      if (locale === 'de') {
        continue;
      }
      expect(read(CATALOGUES[locale], 'accessCode.title'), locale).not.toBe(de.accessCode.title);
      expect(read(CATALOGUES[locale], 'consent.getStarted'), locale).not.toBe(
        de.consent.getStarted
      );
    }
  });

  it('keep the interpolation placeholders of the source', () => {
    const placeholders = (value: string) => (value.match(/{{\s*\w+\s*}}/g) ?? []).sort(byName);
    const interpolated = reference.filter(
      (key) => placeholders(read(de, key) as string).length > 0
    );
    expect(interpolated.length).toBeGreaterThan(0);

    for (const locale of SUPPORTED_UI_LOCALES) {
      for (const key of interpolated) {
        expect(placeholders(read(CATALOGUES[locale], key) as string), `${locale}.${key}`).toEqual(
          placeholders(read(de, key) as string)
        );
      }
    }
  });

  it('keep the export German wording on the screens that had it', () => {
    expect(de.accessCode.title).toBe('Code eingeben');
    expect(de.accessCode.continue).toBe('Weiter');
    expect(de.accessCode.adminLogin).toBe('Admin-Login');
  });

  it('keep the export English wording on the screens that had it', () => {
    expect(en.language.title).toBe('Choose your language');
    expect(en.consent.getStarted).toBe('Get started');
    expect(en.feedback.title).toBe('Share your feedback');
  });

  it('interpolates without i18next plural handling swallowing the key', () => {
    const instance = createI18n('en');
    expect(instance.t('feedback.stars', { count: 3 })).toBe('3 stars');
    expect(instance.t('accessCode.digitLabel', { position: 2 })).toBe('Character 2');
    expect(instance.t('feedback.nps.option', { score: 7 })).toBe('Score 7');
  });
});
