import { useCallback, useState } from 'react';
import { useServices } from '@/app/providers/services';

/**
 * The legacy key, so passing either gate satisfies both and `ProtectedRoute`
 * agrees with this screen instead of contradicting it.
 */
const STORAGE_KEY = 'authenticated';

/** Storage throws outright in some privacy modes, where a refusal is not a bug. */
function read(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function write(value: boolean): void {
  try {
    if (value) {
      sessionStorage.setItem(STORAGE_KEY, 'true');
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // A session that cannot be remembered still works; it just asks again.
  }
}

/**
 * The interim admin gate. Synchronous because the check is a string comparison
 * against a build-time value — when Keycloak replaces it, `signIn` becomes a
 * redirect and this contract changes with it.
 *
 * Session storage rather than nothing: Phase 3 puts a live conversation behind
 * this screen, and a refresh that drops the admin back to a login while a
 * customer is waiting is a real failure.
 */
export function useAdminAuth() {
  const { config } = useServices();
  const [signedIn, setSignedIn] = useState(read);

  const signIn = useCallback(
    (password: string): boolean => {
      if (password !== config.adminPassword) {
        return false;
      }
      write(true);
      setSignedIn(true);
      return true;
    },
    [config.adminPassword]
  );

  const signOut = useCallback(() => {
    write(false);
    setSignedIn(false);
  }, []);

  return { signedIn, signIn, signOut };
}
