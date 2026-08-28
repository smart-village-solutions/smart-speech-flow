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
  // Customer keys must exist in all ten locales. The admin namespace is
  // German and English only and has its own parity test below.
  const customerKeys = (catalogue: Record<string, unknown>) =>
    flatten(catalogue)
      .filter((key) => !key.startsWith('admin.'))
      .sort(byName);
  const reference = customerKeys(de);

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

  it('define exactly the same customer keys', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      expect(customerKeys(CATALOGUES[locale]), locale).toEqual(reference);
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

describe('the admin namespace', () => {
  const ADMIN_LOCALES = ['de', 'en'] as const;
  const adminKeys = (locale: string) =>
    flatten(CATALOGUES[locale as keyof typeof CATALOGUES]).filter((key) =>
      key.startsWith('admin.')
    );

  it('is defined in German and English', () => {
    for (const locale of ADMIN_LOCALES) {
      expect(adminKeys(locale), locale).not.toEqual([]);
    }
  });

  it('defines the same admin keys in German and English', () => {
    expect(adminKeys('en').sort(byName)).toEqual(adminKeys('de').sort(byName));
  });

  // Staff-facing copy. A machine translation into a customer language would
  // read as reviewed and not be, which is the failure the parity test above
  // exists to prevent — so the namespace is deliberately absent there.
  it('is absent from the customer locales', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      if ((ADMIN_LOCALES as readonly string[]).includes(locale)) {
        continue;
      }
      expect(adminKeys(locale), locale).toEqual([]);
    }
  });

  it('has no empty strings', () => {
    for (const locale of ADMIN_LOCALES) {
      for (const key of adminKeys(locale)) {
        expect(read(CATALOGUES[locale], key), `${locale}.${key}`).not.toBe('');
      }
    }
  });

  it('translates the admin screens rather than copying the German', () => {
    expect(en.admin.dashboard.newSession).not.toBe(de.admin.dashboard.newSession);
  });

  // `count` makes i18next look for minutes_one/minutes_other before the base
  // key. The fallback is proven for the customer catalogue above; a silent miss
  // here would render the raw key in the session list.
  it('renders the duration plural rather than swallowing the key', () => {
    const instance = createI18n('de');
    expect(instance.t('admin.sessions.minutes', { count: 8 })).toBe('8 Min.');
    expect(instance.t('admin.sessions.minutes', { count: 1 })).toBe('1 Min.');
  });
});
