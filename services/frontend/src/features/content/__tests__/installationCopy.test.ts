import { describe, expect, it } from 'vitest';
import { toPublicContent } from '@/domain/content/content.mapper';
import { createI18n } from '@/i18n';
import { loginCopy, startpageCopy } from '@/features/content/installationCopy';
import { installationBody } from '@/test/contentFixtures';

const t = createI18n('de').t;
const studio = toPublicContent({
  ...installationBody,
  startpage: { enterCode: 'Studio-Code', send: 'Studio-Weiter', login: 'Studio-Login' },
  login: { headline: 'Studio-Anmeldung', descriptionHtml: '<p>Studio</p>' },
});
const bundledStartpage = { enterCode: 'Code eingeben', send: 'Weiter', login: 'Login' };

describe('startpageCopy', () => {
  it('uses Studio texts on a German screen', () => {
    expect(startpageCopy(studio, 'de', t)).toEqual({
      enterCode: 'Studio-Code',
      send: 'Studio-Weiter',
      login: 'Studio-Login',
    });
  });

  it('uses bundled texts without content', () => {
    expect(startpageCopy(undefined, 'de', t)).toEqual(bundledStartpage);
  });

  it('uses bundled texts for content in another language', () => {
    expect(startpageCopy({ ...studio, locale: 'en-GB' }, 'de', t)).toEqual(bundledStartpage);
  });

  it('falls back per field', () => {
    const copy = startpageCopy(
      { ...studio, startpage: { ...studio.startpage, send: ' ' } },
      'de',
      t
    );

    expect(copy).toEqual({ enterCode: 'Studio-Code', send: 'Weiter', login: 'Studio-Login' });
  });
});

describe('loginCopy', () => {
  it('uses Studio texts on a German screen', () => {
    expect(loginCopy(studio, 'de', t)).toEqual({
      headline: 'Studio-Anmeldung',
      descriptionHtml: '<p>Studio</p>',
    });
  });

  it('turns the bundled instruction into markup', () => {
    expect(loginCopy(undefined, 'de', t)).toEqual({
      headline: 'Login',
      descriptionHtml:
        '<p>Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.</p>',
    });
  });

  it('keeps the bundled instruction when Studio sends a cleared description', () => {
    const cleared = { ...studio, login: { headline: 'Login', descriptionHtml: '<p></p>' } };

    expect(loginCopy(cleared, 'de', t).descriptionHtml).toBe(
      '<p>Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.</p>'
    );
  });

  it('uses bundled texts for content in another language', () => {
    expect(loginCopy({ ...studio, locale: 'en' }, 'de', t).headline).toBe('Login');
  });
});
