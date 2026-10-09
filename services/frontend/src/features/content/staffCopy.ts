import type { TFunction } from 'i18next';
import type { BrandId } from '@/app/config/env';
import type { StaffContent, StaffTexts } from '@/domain/content/content.types';
import type { SystemLoadLevel } from '@/domain/health/health.types';
import { htmlOr, inLocale, textOr } from './resolve';

export interface LoadCopy {
  headline: string;
  levels: Readonly<Record<SystemLoadLevel, string>>;
}

export interface InviteCopy {
  headline: string;
  descriptionHtml: string;
}

export interface StaffCopy {
  headline: string;
  introHtml: string;
  callToAction: string;
  load: LoadCopy;
  invite: InviteCopy;
}

type StudioLoad = StaffTexts['dashboard']['load'];

function loadCopy(load: StudioLoad | undefined, t: TFunction): LoadCopy {
  return {
    headline: textOr(load?.headline, t('admin.load.title')),
    levels: {
      ok: textOr(load?.green, t('admin.load.ok')),
      delayed: textOr(load?.yellow, t('admin.load.delayed')),
      unavailable: textOr(load?.red, t('admin.load.unavailable')),
      // Studio has no label for a load SSF could not read.
      unknown: t('admin.load.unknown'),
    },
  };
}

function inviteCopy(studio: StaffTexts['newConversation'] | undefined, t: TFunction): InviteCopy {
  return {
    headline: textOr(studio?.headline, t('admin.invite.title')),
    descriptionHtml: htmlOr(studio?.descriptionHtml, t('admin.invite.subtitle')),
  };
}

/** Staff texts are in one language (de-DE today); a screen in another keeps bundled copy. */
export function staffCopy(
  content: StaffContent | undefined,
  screenLocale: string,
  t: TFunction,
  brand: BrandId
): StaffCopy {
  const staff = inLocale(content?.staff, screenLocale);
  const dashboard = staff?.dashboard;
  return {
    headline: textOr(dashboard?.headline, t(`admin.dashboard.welcome.${brand}`)),
    introHtml: htmlOr(dashboard?.explanationHtml, t('admin.dashboard.intro')),
    callToAction: textOr(dashboard?.callToAction, t('admin.dashboard.newSession')),
    load: loadCopy(dashboard?.load, t),
    invite: inviteCopy(staff?.newConversation, t),
  };
}
