import { describe, expect, it, vi } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';

const keys = { fingerprint: new Uint8Array(32) } as unknown as UnlockedKeys;

describe('key vault', () => {
  it('holds keys until locked and tells its subscribers', () => {
    const vault = createKeyVault();
    const listener = vi.fn();
    const unsubscribe = vault.subscribe(listener);
    vault.hold(keys);
    expect(vault.current()).toBe(keys);
    vault.lock();
    expect(vault.current()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    vault.hold(keys);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

it('rejects an unlock that finishes after locking, including an already locked vault', () => {
  const vault = createKeyVault();
  const generation = vault.generation();
  vault.lock();
  expect(vault.holdIfCurrent(keys, generation)).toBe(false);
  expect(vault.current()).toBeNull();
  expect(vault.holdIfCurrent(keys, vault.generation())).toBe(true);
  expect(vault.current()).toBe(keys);
});

it('a new tab or reload starts with its own locked vault', () => {
  const currentTab = createKeyVault();
  currentTab.hold(keys);
  expect(createKeyVault().current()).toBeNull();
  expect(currentTab.current()).toBe(keys);
});
