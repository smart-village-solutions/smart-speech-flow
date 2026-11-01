import { afterEach, describe, expect, it, vi } from 'vitest';
import { directionFor, SUPPORTED_UI_LOCALES } from '@/i18n';
import { wordingDirectionFor } from '@/i18n/wordingDirection';

afterEach(() => vi.unstubAllGlobals());

const cases = [
  ['he-IL', 'rtl'],
  ['ar-Latn', 'ltr'],
  ['ar-EG', 'rtl'],
  ['fa-IR', 'rtl'],
  ['de-DE', 'ltr'],
  ['zz-ZZ', 'auto'],
  ['en-Zzzz', 'auto'],
  ['invalid_locale', 'auto'],
] as const;

describe('wordingDirectionFor', () => {
  it.each(cases)('derives source direction for %s', (locale, direction) => {
    expect(wordingDirectionFor(locale)).toBe(direction);
  });

  it('keeps the direction of all bundled UI languages', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      expect(wordingDirectionFor(locale), locale).toBe(directionFor(locale));
    }
    // Source script handling must not change the established UI policy.
    expect(directionFor('he-IL')).toBe('ltr');
    expect(directionFor('ar-Latn')).toBe('rtl');
  });

  it('works in browsers without either text-info API', () => {
    class LegacyLocale extends Intl.Locale {
      getTextInfo = undefined;
      get textInfo() {
        return undefined;
      }
    }
    vi.stubGlobal('Intl', { Locale: LegacyLocale });
    for (const [locale, direction] of cases) {
      expect(wordingDirectionFor(locale), locale).toBe(direction);
    }
  });

  it('lets the text determine direction when Intl.Locale is unavailable', () => {
    vi.stubGlobal('Intl', { Locale: undefined });
    expect(wordingDirectionFor('he-IL')).toBe('auto');
    expect(wordingDirectionFor('ar-Latn')).toBe('auto');
  });

  it('uses an explicit script without requiring maximize support', () => {
    const NativeLocale = Intl.Locale;
    vi.stubGlobal('Intl', {
      Locale: class {
        script: string | undefined;
        constructor(tag: string) {
          this.script = new NativeLocale(tag).script;
        }
      },
    });
    expect(wordingDirectionFor('ar-Latn')).toBe('ltr');
    expect(wordingDirectionFor('en-Hebr')).toBe('rtl');
    expect(wordingDirectionFor('he-IL')).toBe('auto');
  });
});
