import type { AxiosInstance } from 'axios';
import type { PublicKeys } from '@/core/crypto/archive-crypto.port';
import { toBase64Url } from '@/core/crypto/bytes';
import { AppError } from '@/core/http/AppError';
import {
  toEnrolledKey,
  toOwnKey,
  toReenrolled,
  toReenrolmentImpact,
} from './recording.mapper';
import type { EnrolledKey, OwnKey, Reenrolled, ReenrolmentImpact } from './recording.types';

const KEYS = '/api/admin/recording/keys';

/** The gateway's answer when the caller needs a fresh MFA login first. */
export const STEP_UP_REQUIRED = 'STEP_UP_REQUIRED';

export interface RecordingKeysRepository {
  /** Null when the caller has not enrolled yet. */
  ownKey(): Promise<OwnKey | null>;
  enrol(keys: Readonly<PublicKeys>, blob: string): Promise<EnrolledKey>;
  /** A new key for a lost passphrase, replacing the version the caller was shown. */
  reenrol(keys: Readonly<PublicKeys>, blob: string, replacesVersion: number): Promise<Reenrolled>;
  reenrolmentImpact(): Promise<ReenrolmentImpact>;
}

export function createRecordingKeysRepository(http: AxiosInstance): RecordingKeysRepository {
  return {
    async ownKey() {
      try {
        const response = await http.get<unknown>(`${KEYS}/me`);
        return toOwnKey(response.data);
      } catch (error) {
        if (error instanceof AppError && error.serverCode === 'KEY_NOT_ENROLLED') return null;
        throw error;
      }
    },

    async enrol(keys, blob) {
      const response = await http.post<unknown>(KEYS, {
        enc_pub: toBase64Url(keys.encPub),
        sig_pub: toBase64Url(keys.sigPub),
        blob,
      });
      return toEnrolledKey(response.data);
    },

    async reenrol(keys, blob, replacesVersion) {
      const response = await http.post<unknown>(`${KEYS}/reenrolment`, {
        enc_pub: toBase64Url(keys.encPub),
        sig_pub: toBase64Url(keys.sigPub),
        blob,
        replaces_version: replacesVersion,
      });
      return toReenrolled(response.data);
    },

    async reenrolmentImpact() {
      return toReenrolmentImpact((await http.get<unknown>(`${KEYS}/reenrolment`)).data);
    },
  };
}
