import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { PublicContent } from '@/domain/content/content.types';
import { CONTENT_QUERY, contentKeys, toContentState, type ContentState } from './contentQuery';

/** Installation content: logo, legal links, start page, login and installation feedback. */
export function usePublicContent(): ContentState<PublicContent> {
  const { content } = useServices();
  return toContentState(
    useQuery({ queryKey: contentKeys.public, queryFn: () => content.getPublic(), ...CONTENT_QUERY })
  );
}
