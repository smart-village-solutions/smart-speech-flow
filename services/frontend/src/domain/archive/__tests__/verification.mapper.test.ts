import { describe, expect, it } from 'vitest';
import { toBase64Url } from '@/core/crypto/bytes';
import { toAssigned, toCandidates } from '@/domain/archive/verification.mapper';
import { recordBody } from './verificationFixture';

const b = (n: number, length: number) => toBase64Url(new Uint8Array(length).fill(n));
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const ENTRY = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';

describe('verification mapper', () => {
  it('maps an open record without content', () => {
    const record = toAssigned(recordBody({ reviewer_name: 'Rita' }));
    expect(record).toMatchObject({
      status: 'awaiting',
      reviewerSub: 'rita',
      reviewerName: 'Rita',
      decided: null,
    });
    expect(record.reviewerFingerprint).toHaveLength(32);
  });

  it('maps a decided record with its notes, signature, key and stamp', () => {
    const record = toAssigned(
      recordBody({
        status: 'not_approved',
        outcome: 'not_approved',
        reviewed_head: b(3, 32),
        reviewed_head_seq: 4,
        permission_snapshot: ['ssf.recording.review'],
        overall_note: b(9, 40),
        notes: [{ entry_id: ENTRY, key_id: ID, ciphertext: b(1, 40) }],
        signature: b(2, 64),
        reviewer_key: { key_version: 2, enc_pub: b(4, 65), sig_pub: b(5, 65) },
        tsa_token: b(6, 10),
      })
    );
    expect(record.decided).toMatchObject({ outcome: 'not_approved' });
    expect(record.decided?.notes[0].entryId).toBe(ENTRY);
    expect(record.decided?.reviewerKey?.keyVersion).toBe(2);
    expect(record.decided?.tsaToken).toHaveLength(10);
  });

  it('maps candidates and refuses a short fingerprint', () => {
    const candidate = {
      sub: 'rita',
      display_name: 'Rita',
      languages: ['de', 'tr'],
      sworn: true,
      key_version: 1,
      fingerprint: b(1, 32),
      fingerprint_display: 'ABCD',
      enc_pub: b(4, 65),
      sig_pub: b(5, 65),
    };
    expect(toCandidates({ reviewers: [candidate] })[0]).toMatchObject({
      displayName: 'Rita',
      sworn: true,
    });
    expect(() => toCandidates({ reviewers: [{ ...candidate, fingerprint: b(1, 31) }] })).toThrow();
  });
});
