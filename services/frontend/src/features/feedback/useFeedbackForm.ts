import type { QueryKey } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';
import type { ContentSource } from '@/domain/content/content.port';
import type { GuestContent, PublicContent, StaffContent } from '@/domain/content/content.types';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { contentKeys, type ContentState } from '@/features/content/contentQuery';
import { useGuestContent } from '@/features/content/useGuestContent';
import { usePublicContent } from '@/features/content/usePublicContent';
import { useStaffContent } from '@/features/content/useStaffContent';
import {
  guestStudioForm,
  publicStudioForm,
  resolveFeedbackForm,
  staffStudioForm,
  type ResolvedFeedbackForm,
  type StudioFormSource,
} from './resolveFeedbackForm';

/** Built only when the sheet freezes a form, not on every render of an open sheet. */
export interface LiveFeedbackForm {
  resolve: () => ResolvedFeedbackForm;
  /** The fallback, for when the origin's content cannot be read again. */
  resolveBundled: () => ResolvedFeedbackForm;
  /** False while the origin's content request is outstanding. */
  settled: boolean;
  /** The origin's content query, and a read of it past the browser cache. */
  contentKey: QueryKey;
  readFresh: () => Promise<unknown>;
}

interface Contents {
  installation: ContentState<PublicContent>;
  guest: ContentState<GuestContent>;
  staff: ContentState<StaffContent>;
}

interface StudioSource {
  studio: StudioFormSource | undefined;
  settled: boolean;
  contentKey: QueryKey;
  readFresh: (source: ContentSource) => Promise<unknown>;
}

const FRESH = { fresh: true } as const;

function studioSource(origin: FeedbackOrigin, contents: Contents, locale: string): StudioSource {
  switch (origin.kind) {
    case 'public':
      return {
        studio: publicStudioForm(contents.installation.content, locale),
        settled: contents.installation.settled,
        contentKey: contentKeys.public,
        readFresh: (source) => source.getPublic(FRESH),
      };
    case 'guest':
      return {
        studio: guestStudioForm(contents.guest.content, locale),
        settled: contents.guest.settled,
        contentKey: contentKeys.guest(origin.sessionId, locale),
        readFresh: (source) => source.getGuest(origin.sessionId, locale, FRESH),
      };
    case 'staff':
      return {
        studio: staffStudioForm(contents.staff.content, locale),
        settled: contents.staff.settled,
        contentKey: contentKeys.staff,
        readFresh: (source) => source.getStaff(FRESH),
      };
  }
}

/**
 * The form for `origin` as content stands now: Studio's when the audience's
 * content offers one in the screen's language, the bundled form otherwise.
 * Only the origin's own content is asked for, and only while `active` (the sheet
 * is open): a closed sheet keeps its last origin, whose session may have ended.
 */
export function useFeedbackForm(origin: FeedbackOrigin, active: boolean): LiveFeedbackForm {
  const { t } = useTranslation();
  const { locale } = useLocale();
  const { content } = useServices();
  const installation = usePublicContent();
  const guest = useGuestContent(
    active && origin.kind === 'guest' ? origin.sessionId : undefined,
    locale
  );
  const staff = useStaffContent(active && origin.kind === 'staff');
  const { studio, settled, contentKey, readFresh } = studioSource(
    origin,
    { installation, guest, staff },
    locale
  );
  return {
    resolve: () => resolveFeedbackForm(origin, studio, locale, t),
    resolveBundled: () => resolveFeedbackForm(origin, undefined, locale, t),
    settled,
    contentKey,
    readFresh: () => readFresh(content),
  };
}
