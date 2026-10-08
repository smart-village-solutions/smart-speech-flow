import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { StaffContent } from '@/domain/content/content.types';
import { CONTENT_QUERY, contentKeys, toContentState, type ContentState } from './contentQuery';

/**
 * The staff tenant's texts, branding and time zone. A 503 is expected while
 * Studio's login directory is down, and reads as bundled like any failure.
 */
export function useStaffContent(): ContentState<StaffContent> {
  const { content } = useServices();
  return toContentState(
    useQuery({ queryKey: contentKeys.staff, queryFn: () => content.getStaff(), ...CONTENT_QUERY })
  );
}
