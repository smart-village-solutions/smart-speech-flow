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

    expect(store.read()).toBe('second');
    expect(storage.length).toBe(1);
  });

  it('restores the token after a reload', () => {
    const storage = memoryStorage();
    createGuestTokenStore(() => storage).save('AAAA1111', 'kept');

    expect(createGuestTokenStore(() => storage).read()).toBe('kept');
  });

  it('serves the token from memory when storage refuses', () => {
    const store = createGuestTokenStore(throwing);

    store.save('AAAA1111', 'in-memory');

    expect(store.read()).toBe('in-memory');
  });

  it('reads nothing from storage it cannot parse', () => {
    const storage = memoryStorage();
    storage.setItem('ssf.guestToken', 'not json');

    expect(createGuestTokenStore(() => storage).read()).toBeNull();
  });
});
