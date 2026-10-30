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
  /** What a re-enrolment names as the key it replaces (spec §9.6). */
  keyVersion: number;
}

export interface EnrolledKey {
  fingerprint: Bytes;
  fingerprintDisplay: string;
}

/** Active now, or waiting for the emailed confirmation link (spec §9.6). */
export interface Reenrolled extends EnrolledKey {
  status: 'active' | 'pending_confirmation';
}

/** What re-enrolling would cost a custodian: the shares still usable after it. */
export interface ReenrolmentImpact {
  custodian: boolean;
  k: number | null;
  usableAfter: number | null;
}
