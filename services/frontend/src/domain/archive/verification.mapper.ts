import { z } from 'zod';
import { base64Url, sized } from '@/domain/recovery/recovery.mapper';
import type { ReviewerCandidate, VerificationRecord, VerificationSummary } from './archive.types';

const uuid = z.string().uuid();
const status = z.enum([
  'awaiting',
  'in_review',
  'approved',
  'not_approved',
  'declined',
  'withdrawn',
]);

export const summary = z
  .object({
    status: z.enum(['not_verified', 'in_review', 'decided']),
    approved: z.number().int().min(0),
    not_approved: z.number().int().min(0),
  })
  .transform(
    (s): VerificationSummary => ({
      status: s.status,
      approved: s.approved,
      notApproved: s.not_approved,
    })
  );

const note = z.object({ entry_id: uuid, key_id: uuid, ciphertext: base64Url });

export const record = z.object({
  verification_id: uuid,
  status,
  requested_by: z.string(),
  requested_at: z.string(),
  reviewer_sub: z.string(),
  reviewer_name: z.string().nullable().optional(),
  reviewer_key_version: z.number().int().min(1),
  reviewer_fingerprint: sized(32),
  started_at: z.string().nullable(),
  reviewed_head_seq: z.number().int().nullable(),
  reviewed_head: sized(32).nullable(),
  permission_snapshot: z.array(z.string()).nullable(),
  decided_at: z.string().nullable(),
  closed_at: z.string().nullable(),
  close_reason: z.enum(['declined', 'key_retired', 'permission_revoked']).nullable(),
  outcome: z.enum(['approved', 'not_approved']).nullable().optional(),
  overall_note: base64Url.nullable().optional(),
  notes: z.array(note).optional(),
  signature: sized(64).nullable().optional(),
  reviewer_key: z
    .object({ key_version: z.number().int().min(1), enc_pub: sized(65), sig_pub: sized(65) })
    .nullable()
    .optional(),
  tsa_token: base64Url.nullable().optional(),
});

type RecordBody = z.infer<typeof record>;

function decided(r: RecordBody): VerificationRecord['decided'] {
  if (!r.outcome || !r.signature) return null;
  return {
    outcome: r.outcome,
    overallNote: r.overall_note ?? null,
    notes: (r.notes ?? []).map((n) => ({
      entryId: n.entry_id,
      keyId: n.key_id,
      ciphertext: n.ciphertext,
    })),
    signature: r.signature,
    reviewerKey: r.reviewer_key
      ? {
          keyVersion: r.reviewer_key.key_version,
          encPub: r.reviewer_key.enc_pub,
          sigPub: r.reviewer_key.sig_pub,
        }
      : null,
    tsaToken: r.tsa_token ?? null,
  };
}

export function toRecord(r: RecordBody): VerificationRecord {
  return {
    verificationId: r.verification_id,
    status: r.status,
    requestedBy: r.requested_by,
    requestedAt: r.requested_at,
    reviewerSub: r.reviewer_sub,
    reviewerName: r.reviewer_name ?? null,
    reviewerKeyVersion: r.reviewer_key_version,
    reviewerFingerprint: r.reviewer_fingerprint,
    startedAt: r.started_at,
    reviewedHeadSeq: r.reviewed_head_seq,
    reviewedHead: r.reviewed_head,
    permissionSnapshot: r.permission_snapshot,
    decidedAt: r.decided_at,
    closedAt: r.closed_at,
    closeReason: r.close_reason,
    decided: decided(r),
  };
}

const candidate = z.object({
  sub: z.string(),
  display_name: z.string(),
  languages: z.array(z.string()),
  sworn: z.boolean(),
  key_version: z.number().int().min(1),
  fingerprint: sized(32),
  fingerprint_display: z.string(),
  enc_pub: sized(65),
  sig_pub: sized(65),
});

export function toCandidates(body: unknown): ReviewerCandidate[] {
  return z
    .object({ reviewers: z.array(candidate) })
    .parse(body)
    .reviewers.map((c) => ({
      sub: c.sub,
      displayName: c.display_name,
      languages: c.languages,
      sworn: c.sworn,
      keyVersion: c.key_version,
      fingerprint: c.fingerprint,
      fingerprintDisplay: c.fingerprint_display,
      encPub: c.enc_pub,
      sigPub: c.sig_pub,
    }));
}

export function toAssigned(body: unknown): VerificationRecord {
  return toRecord(record.parse(body));
}
