import type { AxiosInstance } from 'axios';
import type { PublicKeys } from '@/core/crypto/archive-crypto.port';
import { toBase64Url } from '@/core/crypto/bytes';
import { AppError } from '@/core/http/AppError';
import { toEnrolledKey, toOwnKey } from './recording.mapper';
import type { EnrolledKey, OwnKey } from './recording.types';

/** The gateway's answer when the caller needs a fresh MFA login first. */
export const STEP_UP_REQUIRED = 'STEP_UP_REQUIRED';

export interface RecordingKeysRepository {
  /** Null when the caller has not enrolled yet. */
  ownKey(): Promise<OwnKey | null>;
  enrol(keys: Readonly<PublicKeys>, blob: string): Promise<EnrolledKey>;
}

export function createRecordingKeysRepository(http: AxiosInstance): RecordingKeysRepository {
  return {
    async ownKey() {
      try {
        const response = await http.get<unknown>('/api/admin/recording/keys/me');
        return toOwnKey(response.data);
      } catch (error) {
        if (error instanceof AppError && error.serverCode === 'KEY_NOT_ENROLLED') return null;
        throw error;
      }
    },

    async enrol(keys, blob) {
      const response = await http.post<unknown>('/api/admin/recording/keys', {
        enc_pub: toBase64Url(keys.encPub),
        sig_pub: toBase64Url(keys.sigPub),
        blob,
      });
      return toEnrolledKey(response.data);
    },
  };
}
