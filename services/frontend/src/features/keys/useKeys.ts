import { useEffect, useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { equalBytes } from '@/core/crypto/bytes';
import type { OwnKey } from '@/domain/recording/recording.types';

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
