import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { INVENTORY_QUERY } from './useKeyInventory';
import type { PendingReenrolment } from '@/domain/recording/recording.types';

const REENROLMENT_IMPACT_QUERY = ['recording', 'reenrolmentImpact'] as const;

export function useUnlockedKeys() {
  const { keyVault } = useServices();
  return useSyncExternalStore(keyVault.subscribe, keyVault.current, keyVault.current);
}

/**
 * The key waiting for its mailed link, re-read whenever the tablet regains focus:
 * the link is usually opened on a phone. When the wait ends, the served key is read
 * again, so the newly active version appears.
 */
export function usePendingReenrolment(): {
  pending: PendingReenrolment | null;
  read: boolean;
  /** The last waiting key this screen saw, once its wait has ended. */
  waitedFor: string | null;
} {
  const { recordingKeys } = useServices();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: REENROLMENT_IMPACT_QUERY,
    queryFn: () => recordingKeys.reenrolmentImpact(),
    refetchOnWindowFocus: true,
  });
  const pending = query.data?.pending ?? null;
  const waited = useRef<string | null>(null);
  const [waitedFor, setWaitedFor] = useState<string | null>(null);
  useEffect(() => {
    if (pending !== null) waited.current = pending.fingerprintDisplay;
    else if (waited.current !== null) {
      setWaitedFor(waited.current);
      waited.current = null;
      void queryClient.invalidateQueries({ queryKey: INVENTORY_QUERY });
    }
  }, [pending, queryClient]);
  return { pending, read: query.isFetchedAfterMount, waitedFor };
}
