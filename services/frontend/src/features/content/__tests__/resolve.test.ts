import { describe, expect, it } from 'vitest';
import { htmlOr, inLocale, sameLanguage, textOr } from '@/features/content/resolve';

describe('sameLanguage', () => {
  it.each([
    ['de-DE', 'de', true],
    ['de', 'de-AT', true],
    ['DE-de', 'de', true],
    ['de-DE', 'en', false],
    ['en-GB', 'de', false],
    ['', 'de', false],
  ])('%j against a %j screen is %s', (content, screenLocale, expected) => {
    expect(sameLanguage(content, screenLocale)).toBe(expected);
  });
});

describe('inLocale', () => {
  it('passes content in the screen language through', () => {
    const content = { locale: 'de-DE', headline: 'Login' };

    expect(inLocale(content, 'de')).toBe(content);
  });

  it('withholds content in another language, and missing content', () => {
    expect(inLocale({ locale: 'de-DE' }, 'en')).toBeUndefined();
    expect(inLocale(null, 'de')).toBeUndefined();
    expect(inLocale(undefined, 'de')).toBeUndefined();
  });
});

describe('textOr', () => {
  it('prefers Studio text and falls back when it is missing or blank', () => {
    expect(textOr('Studio', 'Bundled')).toBe('Studio');
    expect(textOr(undefined, 'Bundled')).toBe('Bundled');
    expect(textOr(null, 'Bundled')).toBe('Bundled');
    expect(textOr('  ', 'Bundled')).toBe('Bundled');
  });
});

describe('htmlOr', () => {
  it('passes Studio markup through', () => {
    expect(htmlOr('<p>Studio</p>', 'Bundled')).toBe('<p>Studio</p>');
  });

  it.each(['<p></p>', '<p><br></p>', '<p> </p><p></p>', '<ul><li></li></ul>'])(
    'treats markup without text, %j, as missing',
    (studio) => {
      expect(htmlOr(studio, 'Bundled')).toBe('<p>Bundled</p>');
    }
  );

  it('escapes bundled text into one paragraph', () => {
    expect(htmlOr(undefined, 'A < B & "C" > D')).toBe('<p>A &lt; B &amp; "C" &gt; D</p>');
    expect(htmlOr(' ', 'Bundled')).toBe('<p>Bundled</p>');
  });
});
