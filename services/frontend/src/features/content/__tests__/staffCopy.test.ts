import { describe, expect, it } from 'vitest';
import { toStaffContent } from '@/domain/content/content.mapper';
import { createI18n } from '@/i18n';
import { staffCopy } from '@/features/content/staffCopy';
import { STUDIO_STAFF, staffContentBodyWith } from '@/test/contentFixtures';

const t = createI18n('de').t;
const studio = toStaffContent(staffContentBodyWith({ marked: true }));

const bundled = {
  headline: 'Willkommen bei KasselDIALOG',
  introHtml:
    '<p>KasselDIALOG stellt einen virtuellen Echtzeit-Dolmetscher bereit. Starten Sie ein neues Gespräch, um sofort mit einer anderssprachigen Person zu kommunizieren — ohne Wartezeit und ohne Vorkenntnisse.</p>',
  callToAction: 'Neues Gespräch starten',
  load: {
    headline: 'Systemauslastung',
    levels: {
      ok: 'Ausreichend Kapazitäten verfügbar',
      delayed: 'Es kann zu kurzen Wartezeiten kommen',
      unavailable: 'Derzeit sind keine weiteren Gespräche möglich',
      unknown: 'Systemauslastung nicht abrufbar',
    },
  },
  invite: {
    headline: 'Neues Gespräch',
    descriptionHtml: '<p>Code oder Link mit dem Gesprächspartner teilen</p>',
  },
};

describe('staffCopy', () => {
  it('uses Studio texts on a German screen', () => {
    expect(staffCopy(studio, 'de', t, 'kassel')).toEqual({
      headline: STUDIO_STAFF.headline,
      introHtml: `<p>${STUDIO_STAFF.intro}</p><p>${STUDIO_STAFF.secondParagraph}</p>`,
      callToAction: STUDIO_STAFF.callToAction,
      load: {
        headline: STUDIO_STAFF.loadHeadline,
        levels: {
          ok: STUDIO_STAFF.green,
          delayed: STUDIO_STAFF.yellow,
          unavailable: STUDIO_STAFF.red,
          unknown: 'Systemauslastung nicht abrufbar',
        },
      },
      invite: {
        headline: STUDIO_STAFF.inviteHeadline,
        descriptionHtml: `<p>${STUDIO_STAFF.inviteDescription}</p>`,
      },
    });
  });

  it('keeps the unknown load label bundled, since Studio has none', () => {
    expect(staffCopy(studio, 'de', t, 'kassel').load.levels.unknown).toBe(
      'Systemauslastung nicht abrufbar'
    );
  });

  it('uses bundled texts without content', () => {
    expect(staffCopy(undefined, 'de', t, 'kassel')).toEqual(bundled);
  });

  it('uses bundled texts for staff texts in another language', () => {
    const english = toStaffContent(staffContentBodyWith({ marked: true, locale: 'en-US' }));
    expect(staffCopy(english, 'de', t, 'kassel')).toEqual(bundled);
  });

  it('uses bundled texts when the staff section was unusable', () => {
    expect(staffCopy({ ...studio, staff: null }, 'de', t, 'kassel')).toEqual(bundled);
  });

  it("welcomes with the brand's bundled headline", () => {
    expect(staffCopy(undefined, 'de', t, 'ssf').headline).toBe(t('admin.dashboard.welcome.ssf'));
  });

  it('falls back per field', () => {
    const staff = studio.staff!;
    const copy = staffCopy(
      {
        ...studio,
        staff: {
          ...staff,
          dashboard: {
            ...staff.dashboard,
            headline: ' ',
            load: { ...staff.dashboard.load, yellow: '' },
          },
          newConversation: { ...staff.newConversation, descriptionHtml: '<p></p>' },
        },
      },
      'de',
      t,
      'kassel'
    );

    expect(copy.headline).toBe(bundled.headline);
    expect(copy.callToAction).toBe(STUDIO_STAFF.callToAction);
    expect(copy.load.levels).toMatchObject({
      ok: STUDIO_STAFF.green,
      delayed: bundled.load.levels.delayed,
    });
    expect(copy.invite).toEqual({
      headline: STUDIO_STAFF.inviteHeadline,
      descriptionHtml: bundled.invite.descriptionHtml,
    });
  });
});
