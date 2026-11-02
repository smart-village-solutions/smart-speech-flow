import type { AxiosInstance } from 'axios';
import { toEnrolledKey, toLinkDetails } from './recording.mapper';
import type { EnrolledKey, LinkDetails } from './recording.types';

// Outside /api/admin: the mailed link works without a login (spec §9.9).
const KEY_CONFIRMATION = '/api/recording/key-confirmation';

export interface KeyConfirmationRepository {
  lookup(token: string): Promise<LinkDetails>;
  /** The new key, once it replaced the old one. */
  confirm(token: string): Promise<EnrolledKey>;
  /** "This wasn't me": the waiting key is dropped, the active one stays. */
  decline(token: string): Promise<void>;
}

export function createKeyConfirmationRepository(http: AxiosInstance): KeyConfirmationRepository {
  return {
    async lookup(token) {
      return toLinkDetails(
        (await http.post<unknown>(`${KEY_CONFIRMATION}/lookup`, { token })).data
      );
    },
    async confirm(token) {
      return toEnrolledKey(
        (await http.post<unknown>(`${KEY_CONFIRMATION}/confirm`, { token })).data
      );
    },
    async decline(token) {
      await http.post(`${KEY_CONFIRMATION}/decline`, { token });
    },
  };
}
