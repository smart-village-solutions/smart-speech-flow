import { z } from 'zod';
import { bytesToBigInt, fromBase64Url } from '@/core/crypto/bytes';
import type { Ceremony, CeremonyState, CustodianCandidate, ReceivedSubshares } from './recovery.types';

export const base64Url = z.string().regex(/^[A-Za-z0-9_-]+$/).transform(fromBase64Url);
export const sized = (length: number) => base64Url.refine((value) => value.length === length, `expected ${length} bytes`);
const point = sized(65);
const scalar = sized(32).transform(bytesToBigInt);

export const participant = z.object({
  holder_index: z.number().int().min(1),
  holder_ref: z.string().min(1),
  kind: z.enum(['custodian', 'paper']),
  display_name: z.string().nullable(),
  enc_pub: point,
  sig_pub: point.nullable(),
  fingerprint: sized(32),
});

export const dealing = z.object({
  dealer_index: z.number().int().min(1),
  commitments: z.array(point).min(1),
  c: scalar,
  s: scalar,
  signature: sized(64),
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
});

const recoveryKey = z.object({
  key_id: z.string(),
  k: z.number().int(),
  n: z.number().int(),
  mode: z.enum(['standard', 'enhanced']),
  transcript_display: z.string(),
  activated_at: z.string(),
});

const failed = z.object({ ceremony_id: z.string(), reason: z.string(), ended_at: z.string() });
const state = z.object({
  recovery_key: recoveryKey.nullable(),
  ceremony: z.unknown(),
  last_failed: failed.nullish(),
  usable_shares: z.number().int().min(0).nullish(),
});

const candidates = z.object({
  candidates: z.array(z.object({ sub: z.string(), display_name: z.string(), fingerprint_display: z.string().nullable() })),
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
          },
    ceremony: parsed.ceremony == null ? null : toCeremony(parsed.ceremony),
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

export function toSubshares(body: unknown): ReceivedSubshares {
  const parsed = subshares.parse(body).subshares;
  return new Map(
    Object.entries(parsed).map(([holder, byDealer]) => [
      Number(holder),
      new Map(Object.entries(byDealer).map(([dealer, sealed]) => [Number(dealer), sealed])),
    ])
  );
}
