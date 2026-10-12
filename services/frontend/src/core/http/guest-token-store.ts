import type { GuestTokenStore } from './guest-token.port';

const STORAGE_KEY = 'ssf.guestToken';

interface Entry {
  sessionId: string;
  token: string;
}

function parse(raw: string | null): Entry | null {
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw) as Partial<Entry>;
    return typeof value.sessionId === 'string' && typeof value.token === 'string'
      ? { sessionId: value.sessionId, token: value.token }
      : null;
  } catch {
    return null;
  }
}

/**
 * Kept in memory and mirrored to storage, so a browser that refuses storage
 * loses the token only on reload rather than on its next request. Storage is
 * read on every lookup, so a tab opened before another tab activated still
 * finds the token without reloading.
 */
export function createGuestTokenStore(storage: () => Storage | null): GuestTokenStore {
  let memory: Entry | null = null;

  const stored = (): Entry | null => {
    try {
      return parse(storage()?.getItem(STORAGE_KEY) ?? null);
    } catch {
      return null;
    }
  };

  return {
    read(sessionId) {
      const match = [stored(), memory].find((entry) => entry?.sessionId === sessionId);
      return match?.token ?? null;
    },
    save(sessionId, token) {
      memory = { sessionId, token };
      try {
        storage()?.setItem(STORAGE_KEY, JSON.stringify(memory));
      } catch {
        // Memory still holds it.
      }
    },
  };
}
