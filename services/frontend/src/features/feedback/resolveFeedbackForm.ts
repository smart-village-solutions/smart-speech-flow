import type { TFunction } from 'i18next';
import type {
  GuestContent,
  PublicContent,
  StaffContent,
  StudioFeedbackForm,
} from '@/domain/content/content.types';
import type {
  FeedbackAudience,
  FeedbackFormSource,
  FeedbackOrigin,
} from '@/domain/feedback/feedback.types';
import type { FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { audienceOf } from '@/domain/feedback/feedbackOrigin';
import { inLocale, studioHtml, textOr } from '@/features/content/resolve';
import { bundledFeedbackForm } from './bundledFeedbackForm';

/** A Studio form with what the v2 body must say about it. */
export interface StudioFormSource {
  form: StudioFeedbackForm;
  revision: string;
  locale: string;
}

/** The form a sheet shows, and everything its submission carries besides the answers. */
export interface ResolvedFeedbackForm {
  origin: FeedbackOrigin;
  definition: FeedbackFormDefinition;
  audience: FeedbackAudience;
  formSource: FeedbackFormSource;
  /** The content revision of a Studio form; null for the bundled one. */
  revision: string | null;
  /** The form's language: Studio content's locale, or the screen's for the bundled form. */
  locale: string;
}

/** Studio's form, with the bundled text wherever Studio's is blank. */
function studioDefinition(
  { headline, questions, noticeHtml, button }: StudioFeedbackForm,
  bundled: FeedbackFormDefinition
): FeedbackFormDefinition {
  const html = studioHtml(noticeHtml);
  return {
    headline: textOr(headline, bundled.headline),
    questions,
    notice: html === undefined ? bundled.notice : { kind: 'html', html },
    button: textOr(button, bundled.button),
  };
}

/** Installation content is in one language (de-DE today); a screen in another gets the bundled form. */
export function publicStudioForm(
  content: PublicContent | undefined,
  screenLocale: string
): StudioFormSource | undefined {
  const installation = inLocale(content, screenLocale);
  return installation?.feedback
    ? { form: installation.feedback, revision: installation.revision, locale: installation.locale }
    : undefined;
}

/** Content fetched for the guest's language, so that language is the form's locale. */
export function guestStudioForm(
  content: GuestContent | undefined,
  language: string
): StudioFormSource | undefined {
  return content?.provided && content.feedback
    ? { form: content.feedback, revision: content.revision, locale: language }
    : undefined;
}

export function staffStudioForm(
  content: StaffContent | undefined,
  screenLocale: string
): StudioFormSource | undefined {
  const staff = inLocale(content?.staff, screenLocale);
  return content && staff?.feedback
    ? { form: staff.feedback, revision: content.revision, locale: staff.locale }
    : undefined;
}

export function resolveFeedbackForm(
  origin: FeedbackOrigin,
  studio: StudioFormSource | undefined,
  screenLocale: string,
  t: TFunction
): ResolvedFeedbackForm {
  const audience = audienceOf(origin);
  const bundled = bundledFeedbackForm(t);
  return studio
    ? {
        origin,
        audience,
        definition: studioDefinition(studio.form, bundled),
        formSource: 'studio',
        revision: studio.revision,
        locale: studio.locale,
      }
    : {
        origin,
        audience,
        definition: bundled,
        formSource: 'bundled',
        revision: null,
        locale: screenLocale,
      };
}
