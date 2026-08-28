import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { AdminSession } from '@/domain/admin/admin.types';

/** The gateway's own default. Ten rows fill the card without scrolling it. */
const LIMIT = 10;

/** Matched to the load card, so the dashboard refreshes as one thing. */
const REFETCH_INTERVAL_MS = 15_000;

export const ADMIN_SESSIONS_KEY = ['adminSessions'] as const;

export function useAdminSessions() {
  const { admin } = useServices();

  return useQuery<AdminSession[]>({
    queryKey: ADMIN_SESSIONS_KEY,
    queryFn: () => admin.listSessions(LIMIT),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}
