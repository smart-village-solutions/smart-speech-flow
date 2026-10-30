import { z } from 'zod';
import { sized } from './recovery.mapper';
import type {
  ApprovalDetail,
  ApprovalsList,
  OwnCandidates,
  RecoveryCandidate,
  RecoveryEmployee,
  RequestProgress,
  RequestSummary,
  ServedPartials,
} from './requests.types';

const uuid = z.string().uuid();
const pair = z.object({ conversation_id: uuid, key_id: uuid });
const status = z.enum(['open', 'completed', 'cancelled', 'expired', 'scope_gone']);
const kind = z.enum(['access', 'key_recovery']);

const summary = z.object({
  request_id: uuid,
  kind,
  requester_sub: z.string(),
  status,
  reason: z.string(),
  created_at: z.string(),
  expires_at: z.string(),
  conversations: z.number().int().min(0),
});

const toPair = (p: z.infer<typeof pair>) => ({
  conversationId: p.conversation_id,
  keyId: p.key_id,
});

function toSummary(row: z.infer<typeof summary>): RequestSummary {
  return {
    requestId: row.request_id,
    kind: row.kind,
    requesterSub: row.requester_sub,
    status: row.status,
    reason: row.reason,
    createdAt: row.created_at,
    expiresAt: row.expires_at,
    conversations: row.conversations,
  };
}

export function toEmployees(body: unknown): RecoveryEmployee[] {
  return z
    .object({
      employees: z.array(z.object({ sub: z.string(), display_name: z.string().nullable() })),
    })
    .parse(body)
    .employees.map((e) => ({ sub: e.sub, displayName: e.display_name }));
}

const candidate = z.object({
  conversation_id: uuid,
  started_at: z.string(),
  ended_at: z.string(),
  retention_until: z.string(),
  legal_hold: z.boolean(),
  incomplete: z.boolean(),
  key_ids: z.array(uuid).min(1),
});

function toCandidate(c: z.infer<typeof candidate>): RecoveryCandidate {
  return {
    conversationId: c.conversation_id,
    startedAt: c.started_at,
    endedAt: c.ended_at,
    retentionUntil: c.retention_until,
    legalHold: c.legal_hold,
    incomplete: c.incomplete,
    keyIds: c.key_ids,
  };
}

export function toRecoveryCandidates(body: unknown): RecoveryCandidate[] {
  return z
    .object({ conversations: z.array(candidate) })
    .parse(body)
    .conversations.map(toCandidate);
}

export function toOwnCandidates(body: unknown): OwnCandidates {
  const count = z.number().int().min(0);
  const parsed = z
    .object({
      conversations: z.array(candidate),
      remaining: z.object({ conversations: count, keys: count }),
    })
    .parse(body);
  return { conversations: parsed.conversations.map(toCandidate), remaining: parsed.remaining };
}

export function toApprovalsList(body: unknown): ApprovalsList {
  const parsed = z.object({ requests: z.array(summary), share_stale: z.boolean() }).parse(body);
  return { requests: parsed.requests.map(toSummary), shareStale: parsed.share_stale };
}

export function toSummaries(body: unknown): RequestSummary[] {
  return z
    .object({ requests: z.array(summary) })
    .parse(body)
    .requests.map(toSummary);
}

export function toScope(body: unknown) {
  return z
    .object({ scope: z.array(pair) })
    .parse(body)
    .scope.map(toPair);
}

export function toProgress(body: unknown): RequestProgress {
  const decision = z.object({
    holder_index: z.number().int().min(1),
    attempt: z.number().int().min(1),
    custodian_sub: z.string(),
    custodian_name: z.string().nullable(),
    decision: z.enum(['approved', 'declined']),
    reason: z.string().nullable(),
    decided_at: z.string(),
    rejected: z.boolean(),
  });
  const parsed = summary
    .extend({ k: z.number().int().min(1), decisions: z.array(decision), scope: z.array(pair) })
    .parse(body);
  return {
    ...toSummary(parsed),
    k: parsed.k,
    decisions: parsed.decisions.map((d) => ({
      holderIndex: d.holder_index,
      attempt: d.attempt,
      custodianSub: d.custodian_sub,
      custodianName: d.custodian_name,
      decision: d.decision,
      reason: d.reason,
      decidedAt: d.decided_at,
      rejected: d.rejected,
    })),
    scope: parsed.scope.map(toPair),
  };
}

const approvalKey = pair.extend({
  employee_sub: z.string(),
  employee_name: z.string().nullable(),
  started_at: z.string(),
  ended_at: z.string(),
  ephemeral: sized(65),
  signer_key_id: z.string(),
  signature: sized(64),
});

const approval = z.object({
  request_id: uuid,
  kind,
  recovery_key_id: uuid,
  requester_sub: z.string(),
  requester_name: z.string().nullable(),
  requester_enc_pub: sized(65),
  requester_sig_pub: sized(65),
  reason: z.string(),
  created_at: z.string(),
  expires_at: z.string(),
  request_signature: sized(64),
  signed_scope: z.array(pair),
  keys: z.array(approvalKey),
  holder_index: z.number().int().min(1),
  attempt: z.number().int().min(1),
  encrypted_share: z.string().min(1),
});

export function toApprovalDetail(body: unknown): ApprovalDetail {
  const a = approval.parse(body);
  return {
    requestId: a.request_id,
    kind: a.kind,
    recoveryKeyId: a.recovery_key_id,
    requesterSub: a.requester_sub,
    requesterName: a.requester_name,
    requesterEncPub: a.requester_enc_pub,
    requesterSigPub: a.requester_sig_pub,
    reason: a.reason,
    createdAt: a.created_at,
    expiresAt: a.expires_at,
    requestSignature: a.request_signature,
    signedScope: a.signed_scope.map(toPair),
    keys: a.keys.map((k) => ({
      ...toPair(k),
      employeeSub: k.employee_sub,
      employeeName: k.employee_name,
      startedAt: k.started_at,
      endedAt: k.ended_at,
      ephemeral: k.ephemeral,
      signerKeyId: k.signer_key_id,
      signature: k.signature,
    })),
    holderIndex: a.holder_index,
    attempt: a.attempt,
    encryptedShare: a.encrypted_share,
  };
}

const served = z.object({
  wraps: z.array(
    pair.extend({ blob: z.string().min(1), creator_ref: z.string(), signature: sized(64) })
  ),
  approvals: z.array(
    z.object({
      holder_index: z.number().int().min(1),
      attempt: z.number().int().min(1),
      signed_partials: z.array(z.object({ key_id: uuid, hash: sized(32) })),
      signature: sized(64),
      partials: z.record(uuid, z.string()),
    })
  ),
  holders_ceremony_id: z.string(),
});

export function toServedPartials(body: unknown): ServedPartials {
  const s = served.parse(body);
  return {
    wraps: s.wraps.map((w) => ({
      ...toPair(w),
      blob: w.blob,
      signerKeyId: w.creator_ref,
      signature: w.signature,
    })),
    approvals: s.approvals.map((a) => ({
      holderIndex: a.holder_index,
      attempt: a.attempt,
      signedPartials: a.signed_partials.map((p) => ({ keyId: p.key_id, hash: p.hash })),
      signature: a.signature,
      partials: new Map(Object.entries(a.partials)),
    })),
    holdersCeremonyId: s.holders_ceremony_id,
  };
}
