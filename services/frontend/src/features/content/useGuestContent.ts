import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { ContentSource } from '@/domain/content/content.port';
import type { GuestContent } from '@/domain/content/content.types';
import { CONTENT_QUERY, contentKeys, toContentState, type ContentState } from './contentQuery';

/** One definition for the hook and the prefetch, so a prefetched entry is the one the screen reads. */
export function guestContentQuery(content: ContentSource, sessionId: string, language: string) {
  return {
    queryKey: contentKeys.guest(sessionId, language),
    queryFn: () => content.getGuest(sessionId, language),
    ...CONTENT_QUERY,
  };
}

/** A guest language's Studio texts and the live storage mode; nothing is asked until both are known. */
export function useGuestContent(
  sessionId: string | undefined,
  language: string | undefined
): ContentState<GuestContent> {
  const { content } = useServices();
  return toContentState(
    useQuery({
      ...guestContentQuery(content, sessionId ?? '', language ?? ''),
      enabled: sessionId !== undefined && language !== undefined,
    })
  );
}
