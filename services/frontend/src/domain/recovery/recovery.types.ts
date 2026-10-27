import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyParticipant, NewDealing, PublishedDealing } from '@/core/crypto/ceremony-crypto.port';

export type { CeremonyParticipant, NewDealing, PublishedDealing };

/** A ceremony in progress, as the gateway lists it (spec §9.2). */
export interface Ceremony {
  ceremonyId: string;
  k: number;
  status: 'dealing' | 'confirming';
  startedBy: string;
  expiresAt: string;
  gatewayKeys: { keyId: string; publicKey: Bytes }[];
  participants: CeremonyParticipant[];
  dealings: PublishedDealing[];
  confirmed: number[];
  paperConfirmed: boolean;
  /** Set once every custodian has dealt. */
  transcriptHash: Bytes | null;
}

export interface RecoveryKey {
  keyId: string;
  k: number;
  n: number;
  mode: 'standard' | 'enhanced';
  transcriptDisplay: string;
  activatedAt: string;
}

/** The tenant's latest ceremony, when it ended without a key. */
export interface FailedCeremony {
  ceremonyId: string;
  /** An abort reason, or 'expired' when it lapsed. */
  reason: string;
  endedAt: string;
}

export interface CeremonyState {
  recoveryKey: RecoveryKey | null;
  ceremony: Ceremony | null;
  lastFailed: FailedCeremony | null;
}

export interface CustodianCandidate {
  sub: string;
  displayName: string;
  /** Null until the custodian has enrolled personal keys; such a custodian cannot be named yet. */
  fingerprintDisplay: string | null;
}

/** Holder index -> dealer index -> sealed sub-share. */
export type ReceivedSubshares = Map<number, Map<number, string>>;

export type AbortReason =
  | 'cancelled'
  | 'device_lost'
  | 'fingerprint_mismatch'
  | 'proof_invalid'
  | 'signature_invalid'
  | 'subshare_invalid'
  | 'transcript_mismatch';
