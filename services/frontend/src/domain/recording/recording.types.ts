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

/** A re-enrolled key waiting for its mailed link (spec §9.9). */
export interface PendingReenrolment {
  fingerprintDisplay: string;
  expiresAt: string;
}

/** What re-enrolling would cost a custodian, and the key already waiting, if any. */
export interface ReenrolmentImpact {
  custodian: boolean;
  k: number | null;
  usableAfter: number | null;
  pending: PendingReenrolment | null;
}

/** What the mailed link's page shows before its owner confirms or declines. */
export interface LinkDetails {
  fingerprintDisplay: string;
  requestedAt: string;
  expiresAt: string;
}
