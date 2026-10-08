import type { TFunction } from 'i18next';
import type { PublicContent } from '@/domain/content/content.types';
import { htmlOr, inLocale, textOr } from './resolve';

export type StartpageCopy = NonNullable<PublicContent['startpage']>;
export type LoginCopy = NonNullable<PublicContent['login']>;

/** Installation content is in one language (de-DE today); a screen in another keeps bundled copy. */
export function startpageCopy(
  content: PublicContent | undefined,
  screenLocale: string,
  t: TFunction
): StartpageCopy {
  const studio: Partial<StartpageCopy> = inLocale(content, screenLocale)?.startpage ?? {};
  return {
    enterCode: textOr(studio.enterCode, t('accessCode.title')),
    send: textOr(studio.send, t('accessCode.continue')),
    login: textOr(studio.login, t('admin.tenantLogin.title')),
  };
}

export function loginCopy(
  content: PublicContent | undefined,
  screenLocale: string,
  t: TFunction
): LoginCopy {
  const studio: Partial<LoginCopy> = inLocale(content, screenLocale)?.login ?? {};
  return {
    headline: textOr(studio.headline, t('admin.tenantLogin.title')),
    descriptionHtml: htmlOr(studio.descriptionHtml, t('admin.tenantLogin.instruction')),
  };
}
