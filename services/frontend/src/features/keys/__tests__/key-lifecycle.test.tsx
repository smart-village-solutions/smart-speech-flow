import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { ServicesProvider } from '@/app/providers/ServicesProvider';
import type { Services } from '@/app/providers/services';
import { createKeyVault } from '@/core/crypto/key-vault';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';
import { useUnlock } from '../useUnlock';
import { useEnrolment } from '../useEnrolment';
import { useReenrolment } from '../useReenrolment';
import { useOwnKey, useVaultFollowsOwnKey } from '../useKeys';

const owner: KeyOwner = { tenantId: 'tenant', userSub: 'alice' };
const keys = { fingerprint: new Uint8Array([1]) } as UnlockedKeys;
const ownKey = { ...keys, blob: 'sealed', keyVersion: 1 } as OwnKey;
const passphrase = 'a sufficiently strong phrase';
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function setup(overrides: Partial<Services> = {}) {
  const vault = createKeyVault();
  const services = { keyVault: vault, ...overrides } as Services;
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ServicesProvider services={services}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ServicesProvider>
  );
  return { vault, wrapper };
}

describe('pending key operations', () => {
  it('does not unlock after an explicit lock while crypto is still running', async () => {
    const pending = deferred<UnlockedKeys>();
    const { vault, wrapper } = setup({
      archiveCrypto: { unlock: () => pending.promise } as Services['archiveCrypto'],
    });
    const hook = renderHook(() => useUnlock(owner, ownKey), { wrapper });
    let submitted!: Promise<unknown>;
    act(() => {
      submitted = hook.result.current.submit(passphrase);
    });
    act(() => vault.lock());
    await act(async () => {
      pending.resolve(keys);
      expect(await submitted).toBe(false);
    });
    expect(vault.current()).toBeNull();
  });

  it('does not enrol after invalidation during passphrase strength checking', async () => {
    const score = deferred<number>();
    const createKeys = vi.fn().mockResolvedValue({ blob: 'sealed', unlocked: keys });
    const enrol = vi.fn();
    const { vault, wrapper } = setup({
      passphraseStrength: { score: () => score.promise },
      archiveCrypto: { createKeys } as Services['archiveCrypto'],
      recordingKeys: { enrol } as Services['recordingKeys'],
    });
    const hook = renderHook(() => useEnrolment(owner), { wrapper });
    let submitted!: Promise<unknown>;
    act(() => {
      submitted = hook.result.current.submit(passphrase, passphrase);
    });
    act(() => vault.lock());
    await act(async () => {
      score.resolve(4);
      expect(await submitted).toBe(false);
    });
    expect(createKeys).not.toHaveBeenCalled();
    expect(enrol).not.toHaveBeenCalled();
    expect(vault.current()).toBeNull();
  });

  it('does not re-hold keys if invalidated while enrolment is posting', async () => {
    const posting = deferred<void>();
    const enrol = vi.fn(() => posting.promise);
    const { vault, wrapper } = setup({
      passphraseStrength: { score: async () => 4 },
      archiveCrypto: {
        createKeys: async () => ({ blob: 'sealed', unlocked: keys }),
      } as Services['archiveCrypto'],
      recordingKeys: { enrol } as Services['recordingKeys'],
    });
    const hook = renderHook(() => useEnrolment(owner), { wrapper });
    let submitted!: Promise<unknown>;
    await act(async () => {
      submitted = hook.result.current.submit(passphrase, passphrase);
    });
    expect(enrol).toHaveBeenCalledOnce();
    act(() => vault.lock());
    await act(async () => {
      posting.resolve();
      expect(await submitted).toBe(false);
    });
    expect(vault.current()).toBeNull();
  });

  it('invalidates pending unlock when the enrolled version changes even while locked', () => {
    const { vault, wrapper } = setup();
    const hook = renderHook(({ key }) => useVaultFollowsOwnKey(key), {
      wrapper,
      initialProps: { key: ownKey },
    });
    const generation = vault.generation();
    hook.rerender({ key: { ...ownKey, keyVersion: 2 } });
    expect(vault.holdIfCurrent(keys, generation)).toBe(false);
  });
});

it('remembers the enrolled version across navigation away from the keys screen', () => {
  const { vault, wrapper } = setup();
  const first = renderHook(() => useVaultFollowsOwnKey(ownKey), { wrapper });
  vault.hold(keys);
  first.unmount();
  expect(vault.current()).toBe(keys);
  renderHook(() => useVaultFollowsOwnKey({ ...ownKey, keyVersion: 2 }), { wrapper });
  expect(vault.current()).toBeNull();
});

it('discards reenrolment results after invalidation while posting', async () => {
  const posting = deferred<never>();
  const { vault, wrapper } = setup({
    passphraseStrength: { score: async () => 4 },
    archiveCrypto: {
      createKeys: async () => ({ blob: 'sealed', unlocked: keys }),
    } as Services['archiveCrypto'],
    recordingKeys: { reenrol: () => posting.promise } as Services['recordingKeys'],
  });
  const hook = renderHook(() => useReenrolment(owner, 1), { wrapper });
  let submitted!: Promise<unknown>;
  await act(async () => {
    submitted = hook.result.current.submit(passphrase, passphrase);
  });
  act(() => vault.lock());
  await act(async () => {
    posting.resolve({ fingerprintDisplay: 'retired' } as never);
    expect(await submitted).toBe(false);
  });
  expect(hook.result.current.result).toBeNull();
});

it('does not let an initial pre-enrolment read erase newly created keys', () => {
  const { vault, wrapper } = setup();
  vault.hold(keys);
  renderHook(() => useVaultFollowsOwnKey(null), { wrapper });
  expect(vault.current()).toBe(keys);
});

it('locks when a previously enrolled key disappears', () => {
  const { vault, wrapper } = setup();
  const hook = renderHook(({ key }: { key: OwnKey | null }) => useVaultFollowsOwnKey(key), {
    wrapper,
    initialProps: { key: ownKey },
  });
  vault.hold(keys);
  hook.rerender({ key: null });
  expect(vault.current()).toBeNull();
});

it('a shared own-key read outside the keys screen invalidates a replaced version', async () => {
  const { vault, wrapper } = setup({
    recordingKeys: {
      ownKey: async () => ({ ...ownKey, keyVersion: 2 }),
    } as Services['recordingKeys'],
  });
  vault.observeKey(ownKey);
  vault.hold(keys);
  const hook = renderHook(() => useOwnKey(), { wrapper });
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
  expect(vault.current()).toBeNull();
});

it('replaces a read begun before enrolment with the newly enrolled server key', async () => {
  const stale = deferred<OwnKey | null>();
  const ownKeyRead = vi.fn().mockReturnValueOnce(stale.promise).mockResolvedValue(ownKey);
  const { vault, wrapper } = setup({
    passphraseStrength: { score: async () => 4 },
    archiveCrypto: {
      createKeys: async () => ({ blob: 'sealed', unlocked: keys }),
    } as Services['archiveCrypto'],
    recordingKeys: {
      ownKey: ownKeyRead,
      enrol: async () => undefined,
    } as unknown as Services['recordingKeys'],
  });
  const hook = renderHook(() => ({ query: useOwnKey(), enrolment: useEnrolment(owner) }), {
    wrapper,
  });
  let submitted!: Promise<boolean>;
  await act(async () => {
    submitted = hook.result.current.enrolment.submit(passphrase, passphrase);
  });
  await act(async () => {
    stale.resolve(null);
    expect(await submitted).toBe(true);
  });
  await waitFor(() => expect(hook.result.current.query.data).toBe(ownKey));
  expect(vault.current()).toBe(keys);
});
