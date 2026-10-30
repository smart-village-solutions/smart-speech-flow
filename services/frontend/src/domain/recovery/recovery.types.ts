import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyParticipant, NewDealing, PublishedDealing } from '@/core/crypto/ceremony-crypto.port';

export type { CeremonyParticipant, NewDealing, PublishedDealing };

/** An old holder dealing in a resharing, under its old index (spec §9.7). */
export interface CeremonyDealer {
  dealerIndex: number;
  holderRef: string;
  kind: 'custodian' | 'paper';
}

/** One completed generation as served, before this browser knows the tenant it belongs to. */
export interface ServedGeneration {
  ceremonyId: string;
  kind: 'generation' | 'resharing';
  k: number;
  transcriptHash: Bytes;
  previousTranscript: Bytes | null;
  gatewayKeys: { keyId: string; publicKey: Bytes }[];
  participants: CeremonyParticipant[];
  dealers: number[];
  dealings: PublishedDealing[];
  signatures: Map<number, Bytes>;
}

export interface ServedChain {
  recoveryKeyId: string;
  firstTranscriptHash: Bytes;
  holdersCeremonyId: string;
  holdersTranscriptHash: Bytes;
  generations: ServedGeneration[];
}

/** What a resharing's dealer opens its share with (spec §9.7). */
export interface DealerKey {
  dealerIndex: number;
  encryptedShare: string;
  keyVersion: number;
  encPub: Bytes;
  sigPub: Bytes;
  fingerprint: Bytes;
  fingerprintDisplay: string;
  blob: string;
}

/** A current holder, for the admin choosing dealers. */
export interface CurrentHolder {
  holderIndex: number;
  holderRef: string;
  kind: 'custodian' | 'paper';
  displayName: string | null;
  /** 'kept': re-enrolled, the old key kept so the share can still deal; 'lost': it cannot. */
  state: 'fresh' | 'kept' | 'lost' | 'paper';
}


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
  kind: 'generation' | 'resharing';
  /** For a resharing: the key it keeps, the generation it replaces, and who deals. */
  recoveryKeyId: string | null;
  previousTranscript: Bytes | null;
  dealers: CeremonyDealer[];
}

export interface RecoveryKey {
  keyId: string;
  k: number;
  n: number;
  mode: 'standard' | 'enhanced';
  transcriptDisplay: string;
  activatedAt: string;
  /** Custodian shares their holders' current keys still open; null when not reported (§9.6). */
  usableShares: number | null;
  holdersCeremonyId: string;
  /** Listed for an org admin only. */
  holders: CurrentHolder[];
  /** The generation a resharing replaced had paper sheets, which must now be destroyed. */
  previousHadPaper: boolean;
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
  /** Served while a resharing runs or once there was one; what the current holders are certified by. */
  chain: ServedChain | null;
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
  | 'transcript_mismatch'
  | 'contribution_invalid'
  | 'chain_invalid';
