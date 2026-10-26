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
