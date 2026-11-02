import i18next from 'i18next';
import { beforeAll, describe, expect, it } from 'vitest';
import type { VerificationRecord } from '@/domain/archive/archive.types';
import { recordMeta } from '@/features/archive/recordMeta';
import { verifiedSummary } from '@/features/archive/summary';
import type { RecordView } from '@/features/archive/verifyRecords';
import en from '@/i18n/locales/en.json';

const base: VerificationRecord = {
  verificationId: 'v',
  status: 'withdrawn',
  requestedBy: 'alice',
  requestedAt: '2026-11-02T10:00:00+00:00',
  reviewerSub: 'rita',
  reviewerName: null,
  reviewerKeyVersion: 1,
  reviewerFingerprint: new Uint8Array(32),
  startedAt: null,
  reviewedHeadSeq: null,
  reviewedHead: null,
  permissionSnapshot: null,
  decidedAt: null,
  closedAt: null,
  closeReason: null,
  decided: null,
};

function view(record: Partial<VerificationRecord>, rest: Partial<RecordView> = {}): RecordView {
  return {
    record: { ...base, ...record },
    state: 'closed',
    overall: null,
    findings: new Map(),
    missingKeys: false,
    stampTime: null,
    entriesAfter: 0,
    ...rest,
  };
}

describe('recordMeta', () => {
  beforeAll(async () => {
    await i18next.init({ lng: 'en', resources: { en: { translation: en } } });
  });

  it('names only what applies, in order', () => {
    const t = i18next.t.bind(i18next);
    expect(recordMeta(t, view({}), 'en').split(' · ')).toHaveLength(1);
    const full = recordMeta(
      t,
      view(
        { decidedAt: '2026-11-02T11:00:00+00:00', closeReason: 'permission_revoked' },
        { entriesAfter: 3, stampTime: '2026-11-02T11:00:05Z', missingKeys: true }
      ),
      'en'
    ).split(' · ');
    expect(full).toHaveLength(6);
    expect(full[2]).toBe(en.admin.archive.verification.closeReason.permission_revoked);
    expect(full[3]).toBe('entries added after this review: 3');
    expect(full[4]).toContain(en.admin.archive.stamp.unverified);
    expect(full[5]).toBe(en.admin.archive.verification.missingKeyNotes);
  });
});

describe('verifiedSummary', () => {
  it('counts only records that passed their check, and shows a review in progress first', () => {
    const decided = (outcome: 'approved' | 'not_approved', state: RecordView['state']) =>
      view({ status: outcome, decided: { outcome } as VerificationRecord['decided'] }, { state });
    expect(verifiedSummary([])).toEqual({ status: 'not_verified', approved: 0, notApproved: 0 });
    expect(
      verifiedSummary([
        decided('approved', 'verified'),
        decided('not_approved', 'verified'),
        decided('approved', 'broken'),
      ])
    ).toEqual({ status: 'decided', approved: 1, notApproved: 1 });
    expect(
      verifiedSummary([
        decided('approved', 'verified'),
        view({ status: 'awaiting' }, { state: 'open' }),
      ])
    ).toEqual({
      status: 'in_review',
      approved: 1,
      notApproved: 0,
    });
    expect(verifiedSummary([decided('approved', 'broken')]).status).toBe('not_verified');
  });
});
