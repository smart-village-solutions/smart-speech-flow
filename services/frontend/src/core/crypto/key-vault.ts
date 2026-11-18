import type { KeyOwner, KeyVault, ListedKey, UnlockedKeys } from './archive-crypto.port';
import { equalBytes } from './bytes';

/** In memory only: a reload, a sign-out or closing the tab locks the keys again. */
export function createKeyVault(): KeyVault {
  let generation = 0;
  let keys: UnlockedKeys | null = null;
  let identity = '';
  let revision = 0;
  let usable = new Map<number, ListedKey>();
  const held = new Map<number, UnlockedKeys>();
  const ownerId = (owner: Readonly<KeyOwner>) => JSON.stringify([owner.tenantId, owner.userSub]);
  const listeners = new Set<() => void>();
  const notify = () => {
    revision += 1;
    for (const listener of listeners) listener();
  };

  return {
    revision: () => revision,
    reconcile(owner, versions) {
      const nextOwner = ownerId(owner);
      const next = new Map(
        versions
          .filter((k) => k.state === 'active' || k.state === 'superseded')
          .map((k) => [k.version, k])
      );
      const changedOwner = nextOwner !== identity;
      const invalidated = [...usable.values()].some((k) => {
        const replacement = next.get(k.version);
        return !replacement || !equalBytes(k.fingerprint, replacement.fingerprint);
      });
      if (changedOwner || invalidated) generation += 1;
      for (const [version, material] of held) {
        const binding = next.get(version);
        if (changedOwner || !binding || !equalBytes(binding.fingerprint, material.fingerprint))
          held.delete(version);
      }
      identity = nextOwner;
      usable = next;
      const active = versions.find((k) => k.state === 'active');
      keys = active ? (held.get(active.version) ?? null) : null;
      notify();
    },
    version(owner, version) {
      return ownerId(owner) === identity ? (held.get(version) ?? null) : null;
    },
    holdVersion(owner, binding, material, startedAt) {
      const enrolled = usable.get(binding.version);
      if (
        material.encPrivate?.extractable ||
        material.sigPrivate?.extractable ||
        generation !== startedAt ||
        ownerId(owner) !== identity ||
        !enrolled ||
        !equalBytes(enrolled.fingerprint, binding.fingerprint) ||
        !equalBytes(binding.fingerprint, material.fingerprint)
      )
        return false;
      held.set(binding.version, material);
      if (enrolled.state === 'active') keys = material;
      notify();
      return true;
    },
    current: () => keys,
    generation: () => generation,
    lock() {
      held.clear();
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
