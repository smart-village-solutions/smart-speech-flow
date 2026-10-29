import { z } from 'zod';
import { base64Url, dealing, participant, sized } from '@/domain/recovery/recovery.mapper';
import type { ArchiveTrust, OpenedConversation, OwnConversation } from './archive.types';

const uuid = z.string().uuid();
const verification = z.literal('not_verified');

const own = z.object({
  conversation_id: uuid,
  employee_sub: z.string(),
  employee_name: z.string().nullable().optional(),
  recovered: z.boolean(),
  started_at: z.string(),
  ended_at: z.string(),
  retention_until: z.string(),
  legal_hold: z.boolean(),
  incomplete: z.boolean(),
  messages: z.number().int().min(0),
  amendments: z.number().int().min(0),
  verification,
});

const opened = z.object({
  conversation: z.object({
    conversation_id: uuid,
    employee_sub: z.string(),
    legal_basis: z.enum(['consent', 'statutory']),
    started_at: z.string(),
    ended_at: z.string(),
    retention_until: z.string(),
    legal_hold: z.boolean(),
    incomplete: z.boolean(),
    verification,
  }),
  windows: z.array(
    z.object({
      window_id: uuid,
      opened_at: z.string(),
      closed_at: z.string().nullable(),
      close_reason: z.string().nullable(),
      pauses: z.array(
        z.object({ at: z.string(), reason: z.string(), resumed_at: z.string().nullable() })
      ),
    })
  ),
  entries: z.array(
    z.object({
      seq: z.number().int().min(1),
      entry_id: uuid,
      kind: z.enum(['message', 'failed', 'consent', 'playback', 'amendment']),
      window_id: uuid.nullable(),
      key_id: uuid,
      objects: z.string(),
      prev_hash: sized(32),
      hash: sized(32),
      signer_key_id: z.string(),
      signature: sized(64),
      created_at: z.string(),
      stored_types: z.array(z.string()),
    })
  ),
  stamps: z.array(
    z.object({ head_seq: z.number().int(), head_hash: sized(32), token: base64Url.nullable() })
  ),
  keys: z.array(
    z.object({
      key_id: uuid,
      epoch: z.number().int().min(1),
      recovery_wrapped: z.boolean(),
      wrap: z
        .object({ blob: z.string().min(1), creator_ref: z.string(), creator_signature: sized(64) })
        .nullable(),
    })
  ),
});

const trust = z.object({
  recovery_key: z.object({ key_id: z.string(), transcript_hash: sized(32) }),
  ceremony: z.object({
    ceremony_id: uuid,
    k: z.number().int().min(1),
    gateway_keys: z.array(z.object({ key_id: z.string(), public_key: sized(65) })),
    participants: z.array(participant).min(1),
    dealings: z.array(dealing),
    transcript_signatures: z.array(
      z.object({ holder_index: z.number().int(), signature: sized(64) })
    ),
  }),
});

/** Each throws on a body it cannot use; callers treat that like any failed request. */
export function toOwnConversations(body: unknown): OwnConversation[] {
  return z
    .object({ conversations: z.array(own) })
    .parse(body)
    .conversations.map((row) => ({
      conversationId: row.conversation_id,
      employeeSub: row.employee_sub,
      employeeName: row.employee_name ?? null,
      recovered: row.recovered,
      startedAt: row.started_at,
      endedAt: row.ended_at,
      retentionUntil: row.retention_until,
      legalHold: row.legal_hold,
      incomplete: row.incomplete,
      messages: row.messages,
      amendments: row.amendments,
      verification: row.verification,
    }));
}

export function toOpened(body: unknown): OpenedConversation {
  const parsed = opened.parse(body);
  const c = parsed.conversation;
  return {
    conversation: {
      conversationId: c.conversation_id,
      employeeSub: c.employee_sub,
      legalBasis: c.legal_basis,
      startedAt: c.started_at,
      endedAt: c.ended_at,
      retentionUntil: c.retention_until,
      legalHold: c.legal_hold,
      incomplete: c.incomplete,
      verification: c.verification,
    },
    windows: parsed.windows.map((w) => ({
      windowId: w.window_id,
      openedAt: w.opened_at,
      closedAt: w.closed_at,
      closeReason: w.close_reason,
      pauses: w.pauses.map((p) => ({ at: p.at, reason: p.reason, resumedAt: p.resumed_at })),
    })),
    entries: parsed.entries.map((e) => ({
      seq: e.seq,
      entryId: e.entry_id,
      kind: e.kind,
      windowId: e.window_id,
      keyId: e.key_id,
      objects: e.objects,
      prevHash: e.prev_hash,
      hash: e.hash,
      signerKeyId: e.signer_key_id,
      signature: e.signature,
      createdAt: e.created_at,
      storedTypes: e.stored_types,
    })),
    stamps: parsed.stamps.map((s) => ({
      headSeq: s.head_seq,
      headHash: s.head_hash,
      token: s.token,
    })),
    keys: parsed.keys.map((k) => ({
      keyId: k.key_id,
      epoch: k.epoch,
      recoveryWrapped: k.recovery_wrapped,
      wrap:
        k.wrap === null
          ? null
          : {
              blob: k.wrap.blob,
              creatorRef: k.wrap.creator_ref,
              creatorSignature: k.wrap.creator_signature,
            },
    })),
  };
}

export function toTrust(body: unknown, tenantId: string): ArchiveTrust {
  const parsed = trust.parse(body);
  const c = parsed.ceremony;
  return {
    recoveryKeyId: parsed.recovery_key.key_id,
    transcriptHash: parsed.recovery_key.transcript_hash,
    facts: {
      tenantId,
      ceremonyId: c.ceremony_id,
      k: c.k,
      gatewayKeys: c.gateway_keys.map((k) => ({ keyId: k.key_id, publicKey: k.public_key })),
      participants: c.participants.map((p) => ({
        holderIndex: p.holder_index,
        holderRef: p.holder_ref,
        kind: p.kind,
        displayName: p.display_name,
        encPub: p.enc_pub,
        sigPub: p.sig_pub,
        fingerprint: p.fingerprint,
      })),
      dealings: c.dealings.map((d) => ({
        dealerIndex: d.dealer_index,
        commitments: d.commitments,
        proof: { c: d.c, s: d.s },
        signature: d.signature,
      })),
    },
    signatures: new Map(c.transcript_signatures.map((s) => [s.holder_index, s.signature])),
  };
}
