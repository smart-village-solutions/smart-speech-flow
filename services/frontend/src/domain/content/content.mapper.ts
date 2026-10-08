import { z } from 'zod';
import { isSafeHttpsUrl } from '@/core/http/url';
import type { GuestContent, GuestLanguage, PublicContent, StaffContent } from './content.types';

function isKnownTimeZone(zone: string): boolean {
  try {
    // The constructor throwing is the check; reading the result only keeps it from being a dropped `new`.
    return new Intl.DateTimeFormat('en', { timeZone: zone }).resolvedOptions().timeZone !== '';
  } catch {
    return false;
  }
}

// Leniency mirrors the gateway: a bad optional part is withdrawn, the rest stays.
const httpsUrl = z.string().refine(isSafeHttpsUrl);
const optionalHttpsUrl = httpsUrl.nullable().catch(null);
const media = z.object({ url: httpsUrl, alternativeText: z.string() }).nullable().catch(null);
const branding = z.object({ logo: media, icon: media });
const optionalText = z
  .string()
  .nullish()
  .transform((value) => value ?? undefined);

const questionBase = {
  id: z.string().min(1),
  headline: optionalText,
  question: z.string(),
  required: z.boolean(),
};

const question = z
  .discriminatedUnion('type', [
    // Zero stars cannot be told apart from no answer.
    z.object({ ...questionBase, type: z.literal('rating'), min: z.int().min(1), max: z.int() }),
    z.object({
      ...questionBase,
      type: z.literal('scale'),
      min: z.int(),
      max: z.int(),
      minLabel: optionalText,
      maxLabel: optionalText,
    }),
    z.object({
      ...questionBase,
      type: z.literal('longText'),
      placeholder: optionalText,
      maxLength: z.int().positive(),
    }),
  ])
  .refine((candidate) => candidate.type === 'longText' || candidate.min <= candidate.max);

/** A form this build cannot render whole is dropped, so the caller shows the bundled one. */
const feedbackForm = z
  .object({
    headline: z.string(),
    questions: z.array(question).min(1),
    noticeHtml: z.string(),
    button: z.string(),
  })
  .nullable()
  .catch(null);

const publicContent = z.object({
  revision: z.string(),
  branding,
  legal: z.object({
    imprintUrl: optionalHttpsUrl,
    privacyPolicyUrl: optionalHttpsUrl,
    accessibilityStatementUrl: optionalHttpsUrl,
  }),
  locale: z.string().min(1),
  startpage: z
    .object({ enterCode: z.string(), send: z.string(), login: z.string() })
    .nullable()
    .catch(null),
  login: z.object({ headline: z.string(), descriptionHtml: z.string() }).nullable().catch(null),
  feedback: feedbackForm,
});

const languageNames = { code: z.string(), name: z.string(), native: z.string() };
const guestLanguages = z.object({
  languages: z.array(
    z.discriminatedUnion('provided', [
      z.object({ ...languageNames, provided: z.literal(false) }),
      z.object({
        ...languageNames,
        provided: z.literal(true),
        nativeName: z.string(),
        icon: media,
      }),
    ])
  ),
});

const storage = z.object({ mode: z.enum(['ask', 'disabled', 'unknown']).catch('unknown') });
const guestContent = z.discriminatedUnion('provided', [
  z.object({ storage, provided: z.literal(false) }),
  z.object({
    storage,
    provided: z.literal(true),
    revision: z.string(),
    explanationHtml: z.string(),
    storageQuestionHtml: z.string().nullable(),
    feedback: feedbackForm,
  }),
]);

const staffTexts = z.object({
  locale: z.string().min(1),
  dashboard: z.object({
    headline: z.string(),
    explanationHtml: z.string(),
    callToAction: z.string(),
    load: z.object({
      headline: z.string(),
      green: z.string(),
      yellow: z.string(),
      red: z.string(),
    }),
  }),
  newConversation: z.object({ headline: z.string(), descriptionHtml: z.string() }),
  feedback: feedbackForm,
});

const staffContent = z.object({
  revision: z.string(),
  timeZone: z.string().refine(isKnownTimeZone).nullable().catch(null),
  branding,
  staff: staffTexts.nullable().catch(null),
  guestLanguageNames: z.record(z.string(), z.string()),
});

/** Each throws on a body it cannot use; callers treat that like any failed request. */
export function toPublicContent(body: unknown): PublicContent {
  return publicContent.parse(body);
}

export function toGuestLanguages(body: unknown): GuestLanguage[] {
  return guestLanguages.parse(body).languages;
}

export function toGuestContent(body: unknown): GuestContent {
  return guestContent.parse(body);
}

export function toStaffContent(body: unknown): StaffContent {
  return staffContent.parse(body);
}
