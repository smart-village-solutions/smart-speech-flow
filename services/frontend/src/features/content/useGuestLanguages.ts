import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { GuestLanguage } from '@/domain/content/content.types';
import { CONTENT_QUERY, contentKeys } from './contentQuery';

/**
 * The session's guest languages, with Studio's names and icons. Unlike Studio
 * texts there is no bundled answer, so a failure keeps the app's retry and is
 * shown.
 */
export function useGuestLanguages(sessionId: string | undefined) {
  const { content } = useServices();
  return useQuery<GuestLanguage[]>({
    queryKey: contentKeys.guestLanguages(sessionId ?? ''),
    queryFn: () => content.getGuestLanguages(sessionId ?? ''),
    enabled: sessionId !== undefined,
    staleTime: CONTENT_QUERY.staleTime,
  });
}
