import { holdTestKeys, testOwner } from '@/test/personalKeys';
import { describe, expect, it, vi } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';

const keys = { fingerprint: new Uint8Array(32) } as unknown as UnlockedKeys;

describe('key vault', () => {
  it('holds keys until locked and tells its subscribers', () => {
    const vault = createKeyVault();
    const listener = vi.fn();
    const unsubscribe = vault.subscribe(listener);
    holdTestKeys(vault, keys);
    expect(vault.current()).toBe(keys);
    vault.lock();
    expect(vault.current()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(3);
    unsubscribe();
    holdTestKeys(vault, keys);
    expect(listener).toHaveBeenCalledTimes(3);
  });
});

it('rejects an unlock that finishes after locking, including an already locked vault', () => {
  const vault = createKeyVault();
  vault.reconcile(testOwner, [{ version: 1, state: 'active', fingerprint: keys.fingerprint }]);
  const generation = vault.generation();
  vault.lock();
  expect(
    vault.holdVersion(testOwner, { version: 1, fingerprint: keys.fingerprint }, keys, generation)
  ).toBe(false);
  expect(vault.current()).toBeNull();
  expect(
    vault.holdVersion(
      testOwner,
      { version: 1, fingerprint: keys.fingerprint },
      keys,
      vault.generation()
    )
  ).toBe(true);
  expect(vault.current()).toBe(keys);
});

it('a new tab or reload starts with its own locked vault', () => {
  const currentTab = createKeyVault();
  holdTestKeys(currentTab, keys);
  expect(createKeyVault().current()).toBeNull();
  expect(currentTab.current()).toBe(keys);
});

it('retains only usable versions for this identity across rotation and rejects a revoked in-flight unlock', () => {
  const vault = createKeyVault();
  const owner = { tenantId: 't', userSub: 'alice' };
  const first = { version: 1, fingerprint: keys.fingerprint, state: 'active' as const };
  const second = { version: 2, fingerprint: new Uint8Array(32).fill(2), state: 'active' as const };
  vault.reconcile(owner, [first]);
  const generation = vault.generation();
  expect(vault.holdVersion(owner, first, keys, generation)).toBe(true);
  vault.reconcile(owner, [{ ...first, state: 'superseded' }, second]);
  expect(vault.version(owner, first.version)).toBe(keys);
  expect(vault.version(owner, second.version)).toBeNull();
  expect(vault.version({ ...owner, userSub: 'bob' }, 1)).toBeNull();
  vault.reconcile(owner, [{ ...first, state: 'revoked' }, second]);
  expect(vault.version(owner, 1)).toBeNull();
  expect(vault.holdVersion(owner, first, keys, generation)).toBe(false);
});
