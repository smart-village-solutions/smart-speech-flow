import type { Bytes } from '@/core/crypto/bytes';

/** The caller's own enrolled key, as the gateway stores it (spec §8.3). */
export interface OwnKey {
  encPub: Bytes;
  sigPub: Bytes;
  /** Passphrase-sealed private keys; the gateway has already removed its server layer. */
  blob: string;
  fingerprint: Bytes;
  fingerprintDisplay: string;
  createdAt: string;
}

export interface EnrolledKey {
  fingerprint: Bytes;
  fingerprintDisplay: string;
}
