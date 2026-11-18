import type { KeyVault, UnlockedKeys } from './archive-crypto.port';
import { equalBytes } from './bytes';

/** In memory only: a reload, a sign-out or closing the tab locks the keys again. */
export function createKeyVault(): KeyVault {
  let generation = 0;
  let observed: Parameters<KeyVault['observeKey']>[0] | undefined;
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
    generation: () => generation,
    observeKey(next) {
      const changed =
        observed != null &&
        (next === null ||
          observed.keyVersion !== next.keyVersion ||
          !equalBytes(observed.fingerprint, next.fingerprint));
      observed = next;
      if (
        changed ||
        (keys !== null && next !== null && !equalBytes(keys.fingerprint, next.fingerprint))
      ) {
        generation += 1;
        keys = null;
        notify();
      }
    },
    holdIfCurrent(next, startedAt) {
      if (startedAt !== generation) return false;
      keys = next;
      notify();
      return true;
    },
    lock() {
      generation += 1;
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
