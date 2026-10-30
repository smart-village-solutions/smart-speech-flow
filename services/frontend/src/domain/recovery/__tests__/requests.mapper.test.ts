import { describe, expect, it } from 'vitest';
import { toBase64Url } from '@/core/crypto/bytes';
import {
  toApprovalDetail,
  toRecoveryCandidates,
  toProgress,
  toApprovalsList,
  toOwnCandidates,
  toServedPartials,
} from '@/domain/recovery/requests.mapper';

const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const KEY = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';
const b = (length: number, fill = 4) => toBase64Url(new Uint8Array(length).fill(fill));

function detail(ephemeral = b(65)) {
  return {
    request_id: ID,
    kind: 'access',
    recovery_key_id: KEY,
    requester_sub: 'sam',
    requester_name: null,
    requester_enc_pub: b(65),
    requester_sig_pub: b(65),
    reason: 'why',
    created_at: '2026-10-29T12:00:00+00:00',
    expires_at: '2026-11-05T12:00:00+00:00',
    request_signature: b(64),
    signed_scope: [{ conversation_id: ID, key_id: KEY }],
    keys: [
      {
        conversation_id: ID,
        key_id: KEY,
        employee_sub: 'alice',
        employee_name: 'Alice',
        started_at: 'a',
        ended_at: 'b',
        ephemeral,
        signer_key_id: 'gw-1',
        signature: b(64),
      },
    ],
    holder_index: 2,
    attempt: 1,
    encrypted_share: '{"v":1}',
  };
}

describe('recovery request mapper', () => {
  it('reads an approval detail, decoding every key and signature', () => {
    const parsed = toApprovalDetail(detail());
    expect(parsed.keys[0].ephemeral).toHaveLength(65);
    expect(parsed.keys[0].employeeName).toBe('Alice');
    expect(parsed.requestSignature).toHaveLength(64);
    expect(parsed.signedScope).toEqual([{ conversationId: ID, keyId: KEY }]);
    expect(parsed.kind).toBe('access');
  });

  it('refuses a kind it does not know', () => {
    expect(() => toApprovalDetail({ ...detail(), kind: 'other' })).toThrow();
  });

  it('reads the own batch with what remains, and the approvals with the stale flag', () => {
    const own = toOwnCandidates({
      conversations: [],
      remaining: { conversations: 3, keys: 9 },
    });
    expect(own).toEqual({ conversations: [], remaining: { conversations: 3, keys: 9 } });
    const listed = toApprovalsList({ requests: [], share_stale: true });
    expect(listed).toEqual({ requests: [], shareStale: true });
  });

  it('refuses an R that is not a 65-byte point', () => {
    expect(() => toApprovalDetail(detail(b(64)))).toThrow();
  });

  it('reads served partials into a map per approval', () => {
    const parsed = toServedPartials({
      wraps: [
        { conversation_id: ID, key_id: KEY, blob: '{}', creator_ref: 'gw-1', signature: b(64) },
      ],
      approvals: [
        {
          holder_index: 1,
          attempt: 2,
          signed_partials: [{ key_id: KEY, hash: b(32) }],
          signature: b(64),
          partials: { [KEY]: '{"p":1}' },
        },
      ],
      holders_ceremony_id: ID,
    });
    expect(parsed.approvals[0].partials.get(KEY)).toBe('{"p":1}');
    expect(parsed.holdersCeremonyId).toBe(ID);
    expect(parsed.wraps[0].signerKeyId).toBe('gw-1');
  });

  it('reads progress and candidates', () => {
    const progress = toProgress({
      request_id: ID,
      kind: 'key_recovery',
      requester_sub: 'sam',
      status: 'open',
      reason: 'why',
      created_at: 'a',
      expires_at: 'b',
      conversations: 1,
      k: 2,
      decisions: [
        {
          holder_index: 1,
          attempt: 1,
          custodian_sub: 'carol',
          custodian_name: null,
          decision: 'approved',
          reason: null,
          decided_at: 'c',
          rejected: true,
        },
      ],
      scope: [{ conversation_id: ID, key_id: KEY }],
    });
    expect(progress.decisions[0].rejected).toBe(true);
    expect(progress.kind).toBe('key_recovery');
    const [candidate] = toRecoveryCandidates({
      conversations: [
        {
          conversation_id: ID,
          started_at: 'a',
          ended_at: 'b',
          retention_until: 'c',
          legal_hold: false,
          incomplete: true,
          key_ids: [KEY],
        },
      ],
    });
    expect(candidate.keyIds).toEqual([KEY]);
  });
});
