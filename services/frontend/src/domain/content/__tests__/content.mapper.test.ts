import { describe, expect, it } from 'vitest';
import {
  toGuestContent,
  toGuestLanguages,
  toPublicContent,
  toStaffContent,
} from '@/domain/content/content.mapper';
import {
  guestContentBody,
  guestLanguagesBody,
  installationBody,
  staffContentBody,
} from '@/test/contentFixtures';

type Mutable = Record<string, unknown>;

function installation(): typeof installationBody {
  return structuredClone(installationBody);
}

describe('toPublicContent', () => {
  it('maps the production installation body', () => {
    const content = toPublicContent(installationBody);

    expect(content.locale).toBe('de-DE');
    expect(content.startpage).toEqual({
      enterCode: 'Code eingeben',
      send: 'Weiter',
      login: 'Login für Nutzer',
    });
    expect(content.legal.accessibilityStatementUrl).toBe(
      'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php'
    );
    expect(content.feedback?.questions.map((question) => question.id)).toEqual([
      'translationQuality',
      'performance',
      'usability',
      'recommendation',
      'improvementIdeas',
    ]);
  });

  it('strips fields it does not know, a display name included', () => {
    const body = {
      ...installation(),
      displayName: 'Stadt Kassel',
      tenant: { id: 'tenant-kassel' },
    };
    (body.login as Mutable).extra = 'ignored';

    const content = toPublicContent(body);

    expect(content).not.toHaveProperty('displayName');
    expect(content).not.toHaveProperty('tenant');
    expect(content.login).toEqual(installationBody.login);
  });

  it.each([
    ['an http:', 'http://dialog.kassel.de/assets/Logo.png'],
    ['a javascript:', 'javascript:alert(1)'],
    ['a data:', 'data:image/png;base64,AAAA'],
    ['a credentialed', 'https://user:pass@dialog.kassel.de/assets/Logo.png'],
    ['a relative', '/assets/Logo.png'],
  ])('turns %s media URL into null and keeps the rest', (_label, url) => {
    const body = installation();
    body.branding = { ...body.branding, logo: { url, alternativeText: 'Logo' } };

    const content = toPublicContent(body);

    expect(content.branding.logo).toBeNull();
    expect(content.branding.icon).toEqual(installationBody.branding.icon);
  });

  it('turns a non-https legal URL into null and keeps the others', () => {
    const body = installation();
    body.legal.imprintUrl = 'http://www.kassel.de/impressum.php';

    expect(toPublicContent(body).legal).toEqual({
      imprintUrl: null,
      privacyPolicyUrl: installationBody.legal.privacyPolicyUrl,
      accessibilityStatementUrl: installationBody.legal.accessibilityStatementUrl,
    });
  });

  it('accepts a missing accessibility statement', () => {
    const body = installation();
    (body.legal as Mutable).accessibilityStatementUrl = null;

    expect(toPublicContent(body).legal.accessibilityStatementUrl).toBeNull();
  });

  it('drops a feedback form with a question type it does not know', () => {
    const body = installation();
    (body.feedback.questions as unknown[]).push({
      id: 'mood',
      headline: null,
      type: 'emoji',
      question: 'How do you feel?',
      required: false,
    });

    const content = toPublicContent(body);

    expect(content.feedback).toBeNull();
    expect(content.startpage.send).toBe('Weiter');
  });

  it('drops a feedback form whose rating starts at zero', () => {
    const body = installation();
    (body.feedback.questions[0] as Mutable).min = 0;

    expect(toPublicContent(body).feedback).toBeNull();
  });

  it('drops a feedback form whose range is inverted', () => {
    const body = installation();
    Object.assign(body.feedback.questions[3], { min: 10, max: 0 });

    expect(toPublicContent(body).feedback).toBeNull();
  });

  it('maps question nulls to absent optionals, in the shape PR 6 renders', () => {
    const body = installation();
    Object.assign(body.feedback.questions[3], { headline: null, minLabel: null });

    expect(toPublicContent(body).feedback?.questions[3]).toEqual({
      id: 'recommendation',
      type: 'scale',
      question:
        'Wie wahrscheinlich empfehlen Sie KasselDIALOG einer Kollegin oder einem Kollegen weiter?',
      required: true,
      min: 0,
      max: 10,
      maxLabel: 'Sehr wahrscheinlich',
    });
  });

  it.each([
    ['start page', 'startpage', { enterCode: 'Code eingeben', send: 7 }],
    ['login', 'login', { headline: 'Login' }],
  ])('withdraws only invalid %s texts', (_label, key, invalid) => {
    const body = { ...installation(), [key]: invalid };

    const content = toPublicContent(body);

    expect(content[key as 'startpage' | 'login']).toBeNull();
    expect(content.legal).toEqual(installationBody.legal);
    expect(content.branding).toEqual(installationBody.branding);
  });

  it.each([
    ['no revision', (body: Mutable) => delete body.revision],
    ['a numeric locale', (body: Mutable) => (body.locale = 7)],
    ['an empty locale', (body: Mutable) => (body.locale = '')],
    ['no legal block', (body: Mutable) => delete body.legal],
  ])('rejects a body with %s', (_label, mutate) => {
    const body = installation() as unknown as Mutable;
    mutate(body);

    expect(() => toPublicContent(body)).toThrow();
  });

  it('rejects a body that is not an object', () => {
    expect(() => toPublicContent('Service Unavailable')).toThrow();
  });
});

describe('toGuestLanguages', () => {
  it('keeps the nine guest languages in order, provided ones with name and icon', () => {
    const languages = toGuestLanguages(guestLanguagesBody);

    expect(languages.map((language) => language.code)).toEqual([
      'en',
      'ar',
      'tr',
      'ru',
      'uk',
      'am',
      'ti',
      'ku',
      'fa',
    ]);
    expect(languages[0]).toEqual({
      code: 'en',
      name: 'English',
      native: 'English',
      provided: true,
      nativeName: 'English',
      icon: { url: 'https://dialog.kassel.de/flags/gb.png', alternativeText: 'Flag EN' },
    });
    expect(languages[1]).toEqual({
      code: 'ar',
      name: 'Arabic',
      native: 'العربية',
      provided: false,
    });
  });

  it('turns an unsafe icon into null without withdrawing the language', () => {
    const body = structuredClone(guestLanguagesBody);
    (body.languages[0] as Mutable).icon = {
      url: 'http://dialog.kassel.de/flags/gb.png',
      alternativeText: 'Flag EN',
    };

    expect(toGuestLanguages(body)[0]).toMatchObject({ code: 'en', provided: true, icon: null });
  });

  it('rejects a provided language without its native name', () => {
    const body = structuredClone(guestLanguagesBody);
    delete (body.languages[0] as Mutable).nativeName;

    expect(() => toGuestLanguages(body)).toThrow();
  });
});

describe('toGuestContent', () => {
  it('maps content Studio provides', () => {
    const content = toGuestContent(guestContentBody('en'));

    expect(content.storage.mode).toBe('ask');
    expect(content.provided && content.storageQuestionHtml).toContain('180 days');
    expect(content.provided && content.feedback?.button).toBe('Send feedback');
  });

  it('maps content Studio does not provide to exactly its mode', () => {
    expect(toGuestContent(guestContentBody('ar'))).toEqual({
      storage: { mode: 'ask' },
      provided: false,
    });
  });

  it('keeps a disabled mode without a storage question', () => {
    const content = toGuestContent({
      ...guestContentBody('en'),
      storage: { mode: 'disabled' },
      storageQuestionHtml: null,
    });

    expect(content).toMatchObject({ storage: { mode: 'disabled' }, storageQuestionHtml: null });
  });

  it('reads a mode it does not know as unknown', () => {
    expect(toGuestContent({ storage: { mode: 'always' }, provided: false }).storage.mode).toBe(
      'unknown'
    );
  });
});

describe('toStaffContent', () => {
  it('maps the production staff body', () => {
    const content = toStaffContent(staffContentBody);

    expect(content.timeZone).toBe('Europe/Berlin');
    expect(content.staff?.locale).toBe('de-DE');
    expect(content.staff?.dashboard.load.red).toContain('keine neuen Gespräche');
    expect(content.staff?.newConversation.descriptionHtml).toBe(
      '<p>Code oder Link mit dem Gesprächspartner teilen</p>'
    );
    expect(content.guestLanguageNames).toEqual({ en: 'Englisch' });
  });

  it('accepts a tenant without staff texts or time zone', () => {
    const content = toStaffContent({ ...staffContentBody, staff: null, timeZone: null });

    expect(content.staff).toBeNull();
    expect(content.timeZone).toBeNull();
  });

  it('withdraws only invalid staff texts, keeping branding, zone and names', () => {
    const body = structuredClone(staffContentBody);
    (body.staff.dashboard.load as Mutable).red = undefined;

    const content = toStaffContent(body);

    expect(content.staff).toBeNull();
    expect(content.branding).toEqual(staffContentBody.branding);
    expect(content.timeZone).toBe('Europe/Berlin');
    expect(content.guestLanguageNames).toEqual({ en: 'Englisch' });
  });

  it('turns a time zone this browser does not know into null', () => {
    expect(
      toStaffContent({ ...staffContentBody, timeZone: 'Mars/Olympus_Mons' }).timeZone
    ).toBeNull();
  });
});
