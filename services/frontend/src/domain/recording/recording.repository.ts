import type { AxiosInstance } from 'axios';
import { z } from 'zod';
import type { PublicKeys } from '@/core/crypto/archive-crypto.port';
import { toBase64Url } from '@/core/crypto/bytes';
import { inventory, readVersion, type KeyInventory } from './keyVersions';
import { toEnrolledKey, toReenrolled, toReenrolmentImpact } from './recording.mapper';
import type { EnrolledKey, OwnKey, Reenrolled, ReenrolmentImpact } from './recording.types';

const KEYS = '/api/admin/recording/keys';

export interface RecordingKeysRepository {
  passphraseFileEnabled(): Promise<boolean>;
  /** Null when the caller has not enrolled yet. */
  versions(): Promise<KeyInventory>;
  version(version: number): Promise<OwnKey>;
  ownKey(): Promise<OwnKey | null>;
  enrol(keys: Readonly<PublicKeys>, blob: string): Promise<EnrolledKey>;
  /** A new key for a lost passphrase, replacing the version the caller was shown. */
  reenrol(keys: Readonly<PublicKeys>, blob: string, replacesVersion: number): Promise<Reenrolled>;
  reenrolmentImpact(): Promise<ReenrolmentImpact>;
}

export function createRecordingKeysRepository(http: AxiosInstance): RecordingKeysRepository {
  return {
    async passphraseFileEnabled() {
      const response = await http.get<unknown>('/api/admin/recording/key-policy');
      return z.object({ passphrase_file_enabled: z.boolean() }).parse(response.data)
        .passphrase_file_enabled;
    },
    async versions() {
      return inventory.parse((await http.get<unknown>('/api/admin/recording/v2/keys/me')).data);
    },
    async version(version) {
      return readVersion(
        (await http.get<unknown>(`/api/admin/recording/v2/keys/me/${version}`)).data,
        version
      );
    },
    async ownKey() {
      const { activeVersion } = await this.versions();
      return activeVersion === null ? null : this.version(activeVersion);
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
