import type { KeyVault, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';
import type { KeyInventory } from '@/domain/recording/keyVersions';
export function personalInventory(active: OwnKey | null, previous: OwnKey[] = []): KeyInventory {
  return {
    activeVersion: active?.keyVersion ?? null,
    versions: [...previous, ...(active ? [active] : [])].map((k) => ({
      ...k,
      version: k.keyVersion,
      state: k === active ? 'active' : 'superseded',
    })),
  };
}

export const testOwner = { tenantId: 'tenant', userSub: 'alice' };
export function holdTestKeys(vault: KeyVault, keys: UnlockedKeys) {
  const binding = { version: 1, state: 'active' as const, fingerprint: keys.fingerprint };
  vault.reconcile(testOwner, [binding]);
  return vault.holdVersion(testOwner, binding, keys, vault.generation());
}
