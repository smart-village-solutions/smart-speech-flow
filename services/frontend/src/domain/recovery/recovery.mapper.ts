import { z } from 'zod';
import { bytesToBigInt, fromBase64Url } from '@/core/crypto/bytes';
import type {
  Ceremony,
  CeremonyState,
  CurrentHolder,
  CustodianCandidate,
  DealerKey,
  LeaverCandidate,
  ReceivedSubshares,
  ServedChain,
  ServedGeneration,
} from './recovery.types';

export const base64Url = z.string().regex(/^[A-Za-z0-9_-]+$/).transform(fromBase64Url);
export const sized = (length: number) => base64Url.refine((value) => value.length === length, `expected ${length} bytes`);
const point = sized(65);
const scalar = sized(32).transform(bytesToBigInt);

const participant = z.object({
  holder_index: z.number().int().min(1),
  holder_ref: z.string().min(1),
  kind: z.enum(['custodian', 'paper']),
  display_name: z.string().nullable(),
  enc_pub: point,
  sig_pub: point.nullable(),
  fingerprint: sized(32),
});

const dealing = z.object({
  dealer_index: z.number().int().min(1),
  commitments: z.array(point).min(1),
  c: scalar,
  s: scalar,
  // Null only for a paper sheet dealing in a resharing (spec §9.7).
  signature: sized(64).nullable(),
});

const ceremony = z.object({
  ceremony_id: z.string().uuid(),
  k: z.number().int().min(1),
  status: z.enum(['dealing', 'confirming']),
  started_by: z.string(),
  expires_at: z.string(),
  gateway_keys: z.array(z.object({ key_id: z.string(), public_key: point })),
  participants: z.array(participant).min(1),
  dealings: z.array(dealing),
  confirmed: z.array(z.number().int()),
  paper_confirmed: z.boolean(),
  transcript_hash: sized(32).nullable(),
  kind: z.enum(['generation', 'resharing']),
  recovery_key_id: z.string().nullable(),
  previous_transcript_hash: sized(32).nullable(),
  dealers: z.array(
    z.object({ dealer_index: z.number().int().min(1), holder_ref: z.string(), kind: z.enum(['custodian', 'paper']) })
  ),
});

const recoveryKey = z.object({
  key_id: z.string(),
  k: z.number().int(),
  n: z.number().int(),
  mode: z.enum(['standard', 'enhanced']),
  transcript_hash: sized(32),
  transcript_display: z.string(),
  activated_at: z.string(),
  holders_ceremony_id: z.string(),
  holders_transcript_hash: sized(32),
});

const holder = z.object({
  holder_index: z.number().int().min(1),
  holder_ref: z.string(),
  kind: z.enum(['custodian', 'paper']),
  display_name: z.string().nullable(),
  state: z.enum(['fresh', 'kept', 'lost', 'paper']),
  left: z.boolean(),
});

const failed = z.object({ ceremony_id: z.string(), reason: z.string(), ended_at: z.string() });
const state = z.object({
  recovery_key: recoveryKey.nullable(),
  ceremony: z.unknown(),
  last_failed: failed.nullish(),
  usable_shares: z.number().int().min(0).nullish(),
  holders: z.array(holder),
  previous_had_paper: z.boolean(),
  chain: z.array(z.unknown()),
});

const dealerKey = z.object({
  dealer_index: z.number().int().min(1),
  encrypted_share: z.string().min(1),
  has_active_key: z.boolean(),
  key: z.object({
    key_version: z.number().int().min(1),
    enc_pub: point,
    sig_pub: point,
    blob: z.string().min(1),
    fingerprint: sized(32),
    fingerprint_display: z.string(),
  }),
});

export const generation = z.object({
  ceremony_id: z.string().uuid(),
  kind: z.enum(['generation', 'resharing']),
  k: z.number().int().min(1),
  transcript_hash: sized(32),
  previous_transcript_hash: sized(32).nullable(),
  gateway_keys: z.array(z.object({ key_id: z.string(), public_key: sized(65) })),
  participants: z.array(participant).min(1),
  dealers: z.array(z.number().int().min(1)),
  dealings: z.array(dealing),
  transcript_signatures: z.array(z.object({ holder_index: z.number().int(), signature: sized(64) })),
});

export const chainKey = z.object({
  key_id: z.string(),
  transcript_hash: sized(32),
  holders_ceremony_id: z.string(),
  holders_transcript_hash: sized(32),
});

function toServedGeneration(g: z.infer<typeof generation>): ServedGeneration {
  return {
    ceremonyId: g.ceremony_id,
    kind: g.kind,
    k: g.k,
    transcriptHash: g.transcript_hash,
    previousTranscript: g.previous_transcript_hash,
    gatewayKeys: g.gateway_keys.map((key) => ({ keyId: key.key_id, publicKey: key.public_key })),
    participants: g.participants.map((p) => ({
      holderIndex: p.holder_index,
      holderRef: p.holder_ref,
      kind: p.kind,
      displayName: p.display_name,
      encPub: p.enc_pub,
      sigPub: p.sig_pub,
      fingerprint: p.fingerprint,
    })),
    dealers: g.dealers,
    dealings: g.dealings.map((d) => ({
      dealerIndex: d.dealer_index,
      commitments: d.commitments,
      proof: { c: d.c, s: d.s },
      signature: d.signature,
    })),
    signatures: new Map(g.transcript_signatures.map((s) => [s.holder_index, s.signature])),
  };
}

export function toServedChain(
  key: z.infer<typeof chainKey>,
  generations: readonly z.infer<typeof generation>[]
): ServedChain {
  return {
    recoveryKeyId: key.key_id,
    firstTranscriptHash: key.transcript_hash,
    holdersCeremonyId: key.holders_ceremony_id,
    holdersTranscriptHash: key.holders_transcript_hash,
    generations: generations.map(toServedGeneration),
  };
}

const candidates = z.object({
  candidates: z.array(z.object({ sub: z.string(), display_name: z.string(), fingerprint_display: z.string().nullable() })),
});

const leavers = z.object({
  candidates: z.array(
    z.object({
      sub: z.string().min(1),
      key_version: z.number().int().min(1),
      fingerprint_display: z.string(),
      enrolled_at: z.string(),
      conversations: z.number().int().min(0),
      last_conversation_at: z.string().nullable(),
      custodian: z.boolean(),
      display_name: z.string().nullable(),
    })
  ),
});

const subshares = z.object({ subshares: z.record(z.string(), z.record(z.string(), z.string())) });

/** Each throws on a body it cannot use; callers treat that like any failed request. */
export function toCeremony(body: unknown): Ceremony {
  const parsed = ceremony.parse(body);
  return {
    ceremonyId: parsed.ceremony_id,
    k: parsed.k,
    status: parsed.status,
    startedBy: parsed.started_by,
    expiresAt: parsed.expires_at,
    gatewayKeys: parsed.gateway_keys.map((key) => ({ keyId: key.key_id, publicKey: key.public_key })),
    participants: parsed.participants.map((p) => ({
      holderIndex: p.holder_index,
      holderRef: p.holder_ref,
      kind: p.kind,
      displayName: p.display_name,
      encPub: p.enc_pub,
      sigPub: p.sig_pub,
      fingerprint: p.fingerprint,
    })),
    dealings: parsed.dealings.map((d) => ({
      dealerIndex: d.dealer_index,
      commitments: d.commitments,
      proof: { c: d.c, s: d.s },
      signature: d.signature,
    })),
    confirmed: parsed.confirmed,
    paperConfirmed: parsed.paper_confirmed,
    transcriptHash: parsed.transcript_hash,
    kind: parsed.kind,
    recoveryKeyId: parsed.recovery_key_id,
    previousTranscript: parsed.previous_transcript_hash,
    dealers: parsed.dealers.map((d) => ({ dealerIndex: d.dealer_index, holderRef: d.holder_ref, kind: d.kind })),
  };
}

function toHolder(h: z.infer<typeof holder>): CurrentHolder {
  return {
    holderIndex: h.holder_index,
    holderRef: h.holder_ref,
    kind: h.kind,
    displayName: h.display_name,
    state: h.state,
    left: h.left,
  };
}

export function toCeremonyState(body: unknown): CeremonyState {
  const parsed = state.parse(body);
  const key = parsed.recovery_key;
  return {
    recoveryKey:
      key === null
        ? null
        : {
            keyId: key.key_id,
            k: key.k,
            n: key.n,
            mode: key.mode,
            transcriptDisplay: key.transcript_display,
            activatedAt: key.activated_at,
            usableShares: parsed.usable_shares ?? null,
            holdersCeremonyId: key.holders_ceremony_id,
            holders: parsed.holders.map(toHolder),
            previousHadPaper: parsed.previous_had_paper,
          },
    ceremony: parsed.ceremony == null ? null : toCeremony(parsed.ceremony),
    chain:
      key === null || parsed.chain.length === 0
        ? null
        : toServedChain(key, parsed.chain.map((g) => generation.parse(g))),
    lastFailed:
      parsed.last_failed == null
        ? null
        : { ceremonyId: parsed.last_failed.ceremony_id, reason: parsed.last_failed.reason, endedAt: parsed.last_failed.ended_at },
  };
}

export function toCandidates(body: unknown): CustodianCandidate[] {
  return candidates.parse(body).candidates.map((c) => ({
    sub: c.sub,
    displayName: c.display_name,
    fingerprintDisplay: c.fingerprint_display,
  }));
}

export function toLeavers(body: unknown): LeaverCandidate[] {
  return leavers.parse(body).candidates.map((c) => ({
    sub: c.sub,
    keyVersion: c.key_version,
    fingerprintDisplay: c.fingerprint_display,
    enrolledAt: c.enrolled_at,
    conversations: c.conversations,
    lastConversationAt: c.last_conversation_at,
    custodian: c.custodian,
    displayName: c.display_name,
  }));
}

export function toSubshares(body: unknown): ReceivedSubshares {
  const parsed = subshares.parse(body).subshares;
  return new Map(
    Object.entries(parsed).map(([holder, byDealer]) => [
      Number(holder),
      new Map(Object.entries(byDealer).map(([dealer, sealed]) => [Number(dealer), sealed])),
    ])
  );
}

export function toDealerKey(body: unknown): DealerKey {
  const parsed = dealerKey.parse(body);
  return {
    dealerIndex: parsed.dealer_index,
    encryptedShare: parsed.encrypted_share,
    keyVersion: parsed.key.key_version,
    encPub: parsed.key.enc_pub,
    sigPub: parsed.key.sig_pub,
    fingerprint: parsed.key.fingerprint,
    fingerprintDisplay: parsed.key.fingerprint_display,
    blob: parsed.key.blob,
    hasActiveKey: parsed.has_active_key,
  };
}
