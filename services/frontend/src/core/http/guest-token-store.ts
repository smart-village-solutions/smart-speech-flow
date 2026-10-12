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
 * loses the token only on reload rather than on its next request.
 */
export function createGuestTokenStore(storage: () => Storage | null): GuestTokenStore {
  let entry: Entry | null = null;
  try {
    entry = parse(storage()?.getItem(STORAGE_KEY) ?? null);
  } catch {
    entry = null;
  }

  return {
    read: () => entry?.token ?? null,
    save(sessionId, token) {
      entry = { sessionId, token };
      try {
        storage()?.setItem(STORAGE_KEY, JSON.stringify(entry));
      } catch {
        // Memory still holds it.
      }
    },
  };
}
