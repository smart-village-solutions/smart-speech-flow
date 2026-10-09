import { describe, expect, it } from 'vitest';
import { toGuestContent, toPublicContent, toStaffContent } from '@/domain/content/content.mapper';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { createI18n } from '@/i18n';
import {
  guestStudioForm,
  publicStudioForm,
  resolveFeedbackForm,
  staffStudioForm,
} from '@/features/feedback/resolveFeedbackForm';
import {
  INSTALLATION_REVISION,
  KASSEL_REVISION,
  guestContentBody,
  installationBody,
  staffContentBody,
} from '@/test/contentFixtures';

const t = createI18n('en').t;
const PUBLIC: FeedbackOrigin = { kind: 'public' };
const GUEST: FeedbackOrigin = { kind: 'guest', sessionId: 'A1B2C3D4' };
const STAFF: FeedbackOrigin = { kind: 'staff', sessionId: null };

const installation = toPublicContent(installationBody);
const english = toGuestContent(guestContentBody('en'));
const staff = toStaffContent(staffContentBody);

describe('the installation form', () => {
  it("is Studio's on a screen in the content's language, with its revision and locale", () => {
    const form = resolveFeedbackForm(PUBLIC, publicStudioForm(installation, 'de'), 'de', t);

    expect(form).toMatchObject({
      origin: PUBLIC,
      formSource: 'studio',
      revision: INSTALLATION_REVISION,
      locale: 'de-DE',
    });
    expect(form.definition.headline).toBe('Feedback geben');
    expect(form.definition.notice).toEqual({
      kind: 'html',
      html: installationBody.feedback.noticeHtml,
    });
    expect(form.definition.questions.map((question) => question.id)).toEqual([
      'translationQuality',
      'performance',
      'usability',
      'recommendation',
      'improvementIdeas',
    ]);
  });

  it('is bundled on a screen in another language, in that language', () => {
    const form = resolveFeedbackForm(PUBLIC, publicStudioForm(installation, 'en'), 'en', t);

    expect(form).toMatchObject({ formSource: 'bundled', revision: null, locale: 'en' });
    expect(form.definition.headline).toBe('Share your feedback');
  });

  it.each([
    ['no content', undefined],
    ['a null form', { ...installation, feedback: null }],
  ])('is bundled with %s', (_name, content) => {
    expect(publicStudioForm(content, 'de')).toBeUndefined();
  });
});

describe('the guest form', () => {
  it("is Studio's for a provided language, with the content's revision and the language", () => {
    const form = resolveFeedbackForm(GUEST, guestStudioForm(english, 'en'), 'en', t);

    expect(form).toMatchObject({
      formSource: 'studio',
      revision: KASSEL_REVISION,
      locale: 'en',
    });
    expect(form.definition.questions[4]).toMatchObject({ placeholder: 'Your ideas or complaints' });
  });

  it('is bundled for a language Studio does not provide', () => {
    const arabic = toGuestContent(guestContentBody('ar'));
    const form = resolveFeedbackForm(GUEST, guestStudioForm(arabic, 'ar'), 'ar', t);

    expect(form).toMatchObject({ formSource: 'bundled', revision: null, locale: 'ar' });
  });

  it.each([
    ['no content', undefined],
    ['a null form', english.provided ? { ...english, feedback: null } : english],
  ])('is bundled with %s', (_name, content) => {
    expect(guestStudioForm(content, 'en')).toBeUndefined();
  });
});

describe('the staff form', () => {
  it("is Studio's in the staff language, with the content's revision and locale", () => {
    const form = resolveFeedbackForm(STAFF, staffStudioForm(staff, 'de'), 'de', t);

    expect(form).toMatchObject({
      formSource: 'studio',
      revision: KASSEL_REVISION,
      locale: 'de-DE',
    });
    expect(form.definition.questions[4]).toMatchObject({
      placeholder: 'Ihre Ideen oder Beschwerden sind willkommen.',
    });
  });

  it.each([
    ['no content', undefined, 'de'],
    ['another screen language', staff, 'en'],
    ['no staff texts', { ...staff, staff: null }, 'de'],
  ])('is bundled with %s', (_name, content, locale) => {
    expect(staffStudioForm(content, locale)).toBeUndefined();
  });

  it('is bundled when the staff form is null', () => {
    const content = toStaffContent(staffContentBody);
    const withoutForm = content.staff
      ? { ...content, staff: { ...content.staff, feedback: null } }
      : content;

    expect(staffStudioForm(withoutForm, 'de')).toBeUndefined();
  });
});

describe('blank Studio texts', () => {
  it('fall back to the bundled headline, button and notice, keeping Studio’s questions', () => {
    if (!english.provided || !english.feedback) throw new Error('English is provided');
    const cleared = {
      ...english,
      feedback: { ...english.feedback, headline: '  ', button: '', noticeHtml: '<p></p>' },
    };

    const form = resolveFeedbackForm(GUEST, guestStudioForm(cleared, 'en'), 'en', t);

    expect(form.formSource).toBe('studio');
    expect(form.definition.headline).toBe('Share your feedback');
    expect(form.definition.button).toBe('Send feedback');
    expect(form.definition.notice.kind).toBe('lines');
    expect(form.definition.questions[4]).toMatchObject({ placeholder: 'Your ideas or complaints' });
  });
});
