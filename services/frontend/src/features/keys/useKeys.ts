import { useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';

export const OWN_KEY_QUERY = ['recording', 'ownKey'] as const;
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
