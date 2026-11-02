import { toBase64Url } from '@/core/crypto/bytes';

const b = (n: number, length: number) => toBase64Url(new Uint8Array(length).fill(n));
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';

/** A record as the gateway serves it (spec §10.7); `changes` overrides any field. */
export const recordBody = (changes: Record<string, unknown> = {}) => ({
  verification_id: ID,
  status: 'awaiting',
  requested_by: 'alice',
  requested_at: '2026-11-02T10:00:00+00:00',
  reviewer_sub: 'rita',
  reviewer_key_version: 1,
  reviewer_fingerprint: b(1, 32),
  started_at: null,
  reviewed_head_seq: null,
  reviewed_head: null,
  permission_snapshot: null,
  decided_at: null,
  closed_at: null,
  close_reason: null,
  ...changes,
});
