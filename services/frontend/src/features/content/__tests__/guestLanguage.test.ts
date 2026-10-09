import { describe, expect, it } from 'vitest';
import { languageChoice } from '@/features/content/guestLanguage';

const turkish = { code: 'tr', name: 'Turkish', native: 'Türkçe' };

describe('languageChoice', () => {
  it('keeps the bundled names and flag when Studio does not provide the language', () => {
    expect(languageChoice({ ...turkish, provided: false })).toEqual({
      code: 'tr',
      native: 'Türkçe',
      english: 'Turkish',
      iconUrl: null,
    });
  });

  it("uses Studio's native name and icon and keeps the bundled English name", () => {
    expect(
      languageChoice({
        ...turkish,
        provided: true,
        nativeName: 'Türkçe (Studio)',
        icon: { url: 'https://studio.example.org/flags/tr.svg', alternativeText: 'TR' },
      })
    ).toEqual({
      code: 'tr',
      native: 'Türkçe (Studio)',
      english: 'Turkish',
      iconUrl: 'https://studio.example.org/flags/tr.svg',
    });
  });

  it('falls back to the bundled flag for a null icon and the bundled name for a blank one', () => {
    expect(languageChoice({ ...turkish, provided: true, nativeName: '  ', icon: null })).toEqual({
      code: 'tr',
      native: 'Türkçe',
      english: 'Turkish',
      iconUrl: null,
    });
  });
});
