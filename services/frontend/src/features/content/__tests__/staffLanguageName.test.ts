import { describe, expect, it, vi } from 'vitest';
import { staffLanguageName } from '@/features/content/staffLanguageName';

/** An engine without ICU data for a language hands the code back. */
const echo = (code: string) => code;

const sources = { studioNames: { en: 'Englisch' }, english: undefined, unknown: 'Sprache offen' };

describe('staffLanguageName', () => {
  it("prefers Studio's staff name", () => {
    expect(staffLanguageName('en', { ...sources, displayName: () => 'nicht Studio' })).toBe(
      'Englisch'
    );
  });

  // Every row resolves its name on each dashboard poll.
  it('does not consult the engine when Studio names the language', () => {
    const displayName = vi.fn(echo);
    staffLanguageName('en', { ...sources, displayName });
    expect(displayName).not.toHaveBeenCalled();
  });

  it('skips a blank Studio name', () => {
    expect(
      staffLanguageName('en', { ...sources, studioNames: { en: ' ' }, displayName: () => 'Intl' })
    ).toBe('Intl');
  });

  it('asks the engine for the German name next', () => {
    expect(staffLanguageName('ar', sources)).toBe('Arabisch');
  });

  it.each(['ku', 'ti', 'am'])(
    'falls back to the bundled English name when the engine cannot name %s',
    (code) => {
      expect(staffLanguageName(code, { ...sources, english: 'Bundled', displayName: echo })).toBe(
        'Bundled'
      );
    }
  );

  it('reads an echo in another case as no name', () => {
    expect(
      staffLanguageName('ku', {
        ...sources,
        english: 'Kurdish',
        displayName: (code) => code.toUpperCase(),
      })
    ).toBe('Kurdish');
  });

  it('says the language is unknown when nothing names the code', () => {
    expect(staffLanguageName('zz', sources)).toBe('Sprache offen');
  });

  it('says the language is unknown when the guest has not chosen one', () => {
    expect(staffLanguageName(null, sources)).toBe('Sprache offen');
  });

  it('survives a code the engine rejects', () => {
    expect(staffLanguageName('1', sources)).toBe('Sprache offen');
  });

  it('never reads an inherited property as a Studio name', () => {
    expect(staffLanguageName('constructor', { ...sources, displayName: echo })).toBe(
      'Sprache offen'
    );
  });
});
