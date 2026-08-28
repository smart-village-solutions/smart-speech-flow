import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';

/**
 * Fast enough to feel immediate across a counter, slow enough to stay one
 * request. The gateway sends the admin no join event — it pings every 30s and
 * expects a pong — so the state is polled rather than pushed. Phase 3 owns the
 * transport; opening a socket here would collide with the one it opens, because
 * `connection_id` is only second-granular and a second connection silently
 * displaces the first.
 */
const POLL_MS = 2000;

/** True once the customer is on the other end of the session. */
export function useJoinWatch(sessionId: string | null): boolean {
  const { session } = useServices();

  const { data } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId ?? ''),
    enabled: sessionId !== null,
    refetchInterval: POLL_MS,
  });

  if (data === undefined) {
    return false;
  }
  return data.status === 'active' || data.customerConnected;
}
