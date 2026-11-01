import type { KeyVault, UnlockedKeys } from './archive-crypto.port';

/** In memory only: a reload, a sign-out or closing the tab locks the keys again. */
export function createKeyVault(): KeyVault {
  let keys: UnlockedKeys | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of listeners) listener();
  };

  return {
    current: () => keys,
    hold(next) {
      keys = next;
      notify();
    },
    lock() {
      keys = null;
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
