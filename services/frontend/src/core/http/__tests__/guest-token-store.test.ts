import { describe, expect, it } from 'vitest';
import { createGuestTokenStore } from '@/core/http/guest-token-store';

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

const throwing = (): Storage => {
  throw new DOMException('denied', 'SecurityError');
};

describe('createGuestTokenStore', () => {
  it('keeps one entry, the latest session', () => {
    const storage = memoryStorage();
    const store = createGuestTokenStore(() => storage);

    store.save('AAAA1111', 'first');
    store.save('BBBB2222', 'second');

    expect(store.read('BBBB2222')).toBe('second');
    expect(store.read('AAAA1111')).toBeNull();
    expect(storage.length).toBe(1);
  });

  it('restores the token after a reload', () => {
    const storage = memoryStorage();
    createGuestTokenStore(() => storage).save('AAAA1111', 'kept');

    expect(createGuestTokenStore(() => storage).read('AAAA1111')).toBe('kept');
  });

  it('serves the token from memory when storage refuses', () => {
    const store = createGuestTokenStore(throwing);

    store.save('AAAA1111', 'in-memory');

    expect(store.read('AAAA1111')).toBe('in-memory');
  });

  it('reads nothing from storage it cannot parse', () => {
    const storage = memoryStorage();
    storage.setItem('ssf.guestToken', 'not json');

    expect(createGuestTokenStore(() => storage).read('AAAA1111')).toBeNull();
  });

  it('sees a token another tab saved after this one started', () => {
    const storage = memoryStorage();
    const thisTab = createGuestTokenStore(() => storage);

    createGuestTokenStore(() => storage).save('AAAA1111', 'from-the-other-tab');

    expect(thisTab.read('AAAA1111')).toBe('from-the-other-tab');
  });

  it('still serves its own token when storage holds another session', () => {
    const storage = memoryStorage();
    const store = createGuestTokenStore(() => storage);
    store.save('AAAA1111', 'mine');
    storage.setItem('ssf.guestToken', JSON.stringify({ sessionId: 'BBBB2222', token: 'theirs' }));

    expect(store.read('AAAA1111')).toBe('mine');
  });
});
