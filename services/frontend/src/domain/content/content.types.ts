import type { FeedbackQuestion } from '@/domain/feedback/feedbackForm.types';

/** A Studio image. Only https: URLs survive the mapper. */
export interface ContentMedia {
  url: string;
  alternativeText: string;
}

export interface ContentBranding {
  logo: ContentMedia | null;
  icon: ContentMedia | null;
}

/** Null where Studio's URL is not https:, so the caller falls back. */
export interface LegalLinks {
  imprintUrl: string | null;
  privacyPolicyUrl: string | null;
  accessibilityStatementUrl: string | null;
}

/**
 * A Studio feedback form. The questions already have PR 6's shape; PR 13 turns
 * `noticeHtml` into an html notice and the whole into a FeedbackFormDefinition.
 */
export interface StudioFeedbackForm {
  headline: string;
  questions: FeedbackQuestion[];
  noticeHtml: string;
  button: string;
}

export interface PublicContent {
  revision: string;
  branding: ContentBranding;
  legal: LegalLinks;
  /** BCP 47, e.g. de-DE. Its texts suit only screens in that language. */
  locale: string;
  /** Null when Studio's is invalid, so legal links and branding stay usable. */
  startpage: { enterCode: string; send: string; login: string } | null;
  login: { headline: string; descriptionHtml: string } | null;
  feedback: StudioFeedbackForm | null;
}

interface GuestLanguageNames {
  code: string;
  name: string;
  native: string;
}

export type GuestLanguage =
  | (GuestLanguageNames & { provided: false })
  | (GuestLanguageNames & { provided: true; nativeName: string; icon: ContentMedia | null });

/** `unknown` when the gateway could not read the mode live. */
export type StorageMode = 'ask' | 'disabled' | 'unknown';

export type GuestContent =
  | { storage: { mode: StorageMode }; provided: false }
  | {
      storage: { mode: StorageMode };
      provided: true;
      revision: string;
      explanationHtml: string;
      /** Null when the tenant's mode is `disabled`. */
      storageQuestionHtml: string | null;
      feedback: StudioFeedbackForm | null;
    };

export interface StaffTexts {
  locale: string;
  dashboard: {
    headline: string;
    explanationHtml: string;
    callToAction: string;
    load: { headline: string; green: string; yellow: string; red: string };
  };
  newConversation: { headline: string; descriptionHtml: string };
  feedback: StudioFeedbackForm | null;
}

export interface StaffContent {
  revision: string;
  /** IANA zone; null when Studio sends none or this browser does not know it. */
  timeZone: string | null;
  branding: ContentBranding;
  staff: StaffTexts | null;
  /** SSF language code to its name in the staff language. */
  guestLanguageNames: Record<string, string>;
}
