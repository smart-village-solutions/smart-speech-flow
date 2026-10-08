import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { GuestContent } from '@/domain/content/content.types';
import { CONTENT_QUERY, contentKeys, toContentState, type ContentState } from './contentQuery';

/** A guest language's Studio texts and the live storage mode; nothing is asked until both are known. */
export function useGuestContent(
  sessionId: string | undefined,
  language: string | undefined
): ContentState<GuestContent> {
  const { content } = useServices();
  return toContentState(
    useQuery({
      queryKey: contentKeys.guest(sessionId ?? '', language ?? ''),
      queryFn: () => content.getGuest(sessionId ?? '', language ?? ''),
      enabled: sessionId !== undefined && language !== undefined,
      ...CONTENT_QUERY,
    })
  );
}
