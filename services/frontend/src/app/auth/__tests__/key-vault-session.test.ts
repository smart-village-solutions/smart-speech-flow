import { holdTestKeys, testOwner } from '@/test/personalKeys';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { followKeycloakIdentity } from '../key-vault-session';

const state = vi.hoisted(() => ({
  identity: null as KeyOwner | null,
  authorization: new Set<() => void>(),
  expiration: new Set<() => void>(),
}));
vi.mock('../keycloak', () => ({
  getAdminIdentity: () => state.identity,
  subscribeToKeycloakAuthorization: (listener: () => void) => {
    state.authorization.add(listener);
    return () => state.authorization.delete(listener);
  },
  subscribeToKeycloakExpiration: (listener: () => void) => {
    state.expiration.add(listener);
    return () => state.expiration.delete(listener);
  },
}));
const keys = { fingerprint: new Uint8Array([1]) } as UnlockedKeys;
function notify() {
  for (const listener of state.authorization) listener();
}

describe('tab vault authentication lifetime', () => {
  beforeEach(() => {
    state.identity = { tenantId: 'tenant', userSub: 'alice' };
    state.authorization.clear();
    state.expiration.clear();
  });

  it('preserves keys and pending unlocks through same-identity token refresh', () => {
    const vault = createKeyVault();
    const stop = followKeycloakIdentity(vault);
    holdTestKeys(vault, keys);
    const generation = vault.generation();
    state.identity = { ...state.identity! };
    notify();
    expect(vault.current()).toBe(keys);
    expect(vault.generation()).toBe(generation);
    stop();
  });

  it.each(['logout', 'account', 'tenant'])(
    'locks keys and pending unlocks on %s change',
    (change) => {
      const vault = createKeyVault();
      const stop = followKeycloakIdentity(vault);
      holdTestKeys(vault, keys);
      const generation = vault.generation();
      state.identity =
        change === 'logout'
          ? null
          : {
              tenantId: change === 'tenant' ? 'other' : 'tenant',
              userSub: change === 'account' ? 'bob' : 'alice',
            };
      notify();
      expect(vault.current()).toBeNull();
      expect(
        vault.holdVersion(
          testOwner,
          { version: 1, fingerprint: keys.fingerprint },
          keys,
          generation
        )
      ).toBe(false);
      stop();
    }
  );

  it('locks on detected expiry and on disposal, with no live subscription after disposal', () => {
    const vault = createKeyVault();
    const stop = followKeycloakIdentity(vault);
    holdTestKeys(vault, keys);
    for (const listener of state.expiration) listener();
    expect(vault.current()).toBeNull();
    holdTestKeys(vault, keys);
    stop();
    expect(vault.current()).toBeNull();
    expect(state.authorization.size).toBe(0);
    expect(state.expiration.size).toBe(0);
  });
});
