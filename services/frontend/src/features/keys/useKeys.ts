import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { equalBytes } from '@/core/crypto/bytes';
import type { OwnKey, PendingReenrolment } from '@/domain/recording/recording.types';

export const OWN_KEY_QUERY = ['recording', 'ownKey'] as const;
const REENROLMENT_IMPACT_QUERY = ['recording', 'reenrolmentImpact'] as const;
/** The staff view the step-up redirect returns to. */
export const KEYS_VIEW = 'keys';

export function useOwnKey() {
  const { recordingKeys } = useServices();
  return useQuery({ queryKey: OWN_KEY_QUERY, queryFn: () => recordingKeys.ownKey() });
}

export function useUnlockedKeys() {
  const { keyVault } = useServices();
  return useSyncExternalStore(keyVault.subscribe, keyVault.current, keyVault.current);
}

export function useReenrolmentImpact() {
  const { recordingKeys } = useServices();
  return useQuery({
    queryKey: REENROLMENT_IMPACT_QUERY,
    queryFn: () => recordingKeys.reenrolmentImpact(),
  });
}

/**
 * The key waiting for its mailed link, re-read whenever the tablet regains focus:
 * the link is usually opened on a phone. When the wait ends, the served key is read
 * again, so a confirmed key shows up and the vault lets go of the old one.
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
      void queryClient.invalidateQueries({ queryKey: OWN_KEY_QUERY });
    }
  }, [pending, queryClient]);
  return { pending, read: query.isFetchedAfterMount, waitedFor };
}

/**
 * Locks a vault that holds a key the gateway no longer serves: a re-enrolment
 * confirmed from the mailed link on another device retired it (spec §9.9).
 * Only a newly served key is checked; a key just put in the vault is ahead of it.
 */
export function useVaultFollowsOwnKey(ownKey: OwnKey | null | undefined) {
  const { keyVault } = useServices();
  useEffect(() => {
    const unlocked = keyVault.current();
    if (ownKey == null || unlocked === null) return;
    if (!equalBytes(unlocked.fingerprint, ownKey.fingerprint)) keyVault.lock();
  }, [keyVault, ownKey]);
}
