import { describe, expect, it, vi } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { CeremonyCheckError } from '@/core/crypto/ceremony-crypto.port';
import { RecoveryCheckError } from '@/core/crypto/recovery-crypto.port';
import { RecoveryRefusedError } from '@/domain/recovery/requests.repository';
import type { ApprovalDetail } from '@/domain/recovery/requests.types';
import {
  type RecoveryDeps,
  approveOnce,
  combineOnce,
  faultOf,
  fileOnce,
} from '@/features/recovery/steps';

const identity = { tenantId: 'tenant-kassel', userSub: 'sam' };
const keys = { sigPrivate: {} as CryptoKey } as UnlockedKeys;
const C1 = 'c1';
const C2 = 'c2';

function deps(overrides: Partial<Record<string, unknown>> = {}) {
  const trust = {
    recoveryKeyId: 'rk-1',
    transcriptHash: new Uint8Array(32),
    facts: {},
    signatures: new Map(),
  };
  const recoveryRequests = {
    file: vi.fn().mockResolvedValue([]),
    partials: vi.fn().mockResolvedValue({ wraps: [], approvals: [] }),
    reject: vi.fn().mockResolvedValue(undefined),
    reportIntegrity: vi.fn().mockResolvedValue(undefined),
    storeWraps: vi.fn().mockResolvedValue([]),
    approve: vi.fn().mockResolvedValue(undefined),
  };
  const recoveryCrypto = {
    signRequest: vi.fn().mockResolvedValue(new Uint8Array(64)),
    combine: vi.fn().mockResolvedValue({ wraps: [], rejections: [], integrity: [] }),
    approve: vi.fn().mockResolvedValue({
      partials: new Map([['k1', '{p}']]),
      signature: new Uint8Array(64).fill(7),
    }),
  };
  const ceremonyCrypto = {
    certifyTrust: vi.fn().mockResolvedValue({ k: 2, recoveryKeyId: 'rk-1' }),
  };
  const archive = { trust: vi.fn().mockResolvedValue(trust) };
  return {
    archive,
    ceremonyCrypto,
    recoveryCrypto,
    recoveryRequests,
    ...overrides,
  } as unknown as RecoveryDeps & {
    recoveryRequests: typeof recoveryRequests;
    recoveryCrypto: typeof recoveryCrypto;
    ceremonyCrypto: typeof ceremonyCrypto;
  };
}

const candidate = (conversationId: string, keyIds: string[]) => ({
  conversationId,
  startedAt: 'a',
  endedAt: 'b',
  retentionUntil: 'c',
  legalHold: false,
  incomplete: false,
  keyIds,
});

describe('filing', () => {
  it('signs every key of every ticked conversation under the certified recovery key, then files that request', async () => {
    const d = deps();
    await fileOnce(d, identity, keys, {
      reason: 'why',
      candidates: [candidate(C1, ['k1', 'k2']), candidate(C2, ['k3'])],
    });

    const [signed] = d.recoveryCrypto.signRequest.mock.calls[0];
    expect(signed.scope).toEqual([
      { conversationId: C1, keyId: 'k1' },
      { conversationId: C1, keyId: 'k2' },
      { conversationId: C2, keyId: 'k3' },
    ]);
    expect(signed.recoveryKeyId).toBe('rk-1');
    const [filed] = d.recoveryRequests.file.mock.calls[0];
    expect(filed.requestId).toBe(signed.requestId);
    expect(filed.conversationIds).toEqual([C1, C2]);
    expect(d.ceremonyCrypto.certifyTrust).toHaveBeenCalled();
  });
});

describe('combining', () => {
  it('stores the wraps once k approvals combine', async () => {
    const d = deps();
    expect(await combineOnce(d, identity, keys, 'r1')).toEqual({ kind: 'done' });
    expect(d.recoveryRequests.storeWraps).toHaveBeenCalledWith('r1', []);
  });

  it('reports each rejection and waits when too few remain', async () => {
    const d = deps();
    const rejection = { holderIndex: 2, attempt: 1, fault: 'proof_invalid' };
    d.recoveryCrypto.combine.mockResolvedValue({
      wraps: null,
      rejections: [rejection],
      integrity: [],
    });

    expect(await combineOnce(d, identity, keys, 'r1')).toEqual({ kind: 'waiting', rejected: [2] });
    expect(d.recoveryRequests.reject).toHaveBeenCalledWith('r1', rejection);
    expect(d.recoveryRequests.storeWraps).not.toHaveBeenCalled();
  });

  it('a damaged recovery wrap stores nothing and is reported', async () => {
    const d = deps();
    d.recoveryCrypto.combine.mockResolvedValue({
      wraps: [],
      rejections: [],
      integrity: ['wrap_damaged'],
    });

    expect(await combineOnce(d, identity, keys, 'r1')).toEqual({
      kind: 'damaged',
      stages: ['wrap_damaged'],
    });
    expect(d.recoveryRequests.reportIntegrity).toHaveBeenCalledWith('r1', 'wrap_damaged');
    expect(d.recoveryRequests.storeWraps).not.toHaveBeenCalled();
  });

  it('a transcript that does not certify is reported and nothing is fetched', async () => {
    const d = deps();
    d.ceremonyCrypto.certifyTrust.mockRejectedValue(new CeremonyCheckError('transcript_mismatch'));

    expect(await combineOnce(d, identity, keys, 'r1')).toEqual({
      kind: 'damaged',
      stages: ['trust'],
    });
    expect(d.recoveryRequests.reportIntegrity).toHaveBeenCalledWith('r1', 'trust');
    expect(d.recoveryRequests.partials).not.toHaveBeenCalled();
  });
});

describe('approving', () => {
  const detail = {
    requestId: 'r1',
    recoveryKeyId: 'rk-1',
    requesterSub: 'sam',
    requesterEncPub: new Uint8Array(65),
    requesterSigPub: new Uint8Array(65),
    reason: 'why',
    requestSignature: new Uint8Array(64),
    signedScope: [],
    keys: [],
    holderIndex: 2,
    attempt: 1,
    encryptedShare: '{}',
  } as unknown as ApprovalDetail;

  it('posts exactly the partials and signature the crypto returned', async () => {
    const d = deps();
    const confirmed = new Uint8Array(32).fill(9);
    await approveOnce(d, { ...identity, userSub: 'carol' }, keys, detail, confirmed);
    const [facts, , , caller] = d.recoveryCrypto.approve.mock.calls[0];
    expect(caller).toBe('carol');
    expect(facts.confirmedFingerprint).toBe(confirmed);
    expect(d.recoveryRequests.approve).toHaveBeenCalledWith(
      'r1',
      new Map([['k1', '{p}']]),
      new Uint8Array(64).fill(7)
    );
  });

  it('a failed check posts nothing', async () => {
    const d = deps();
    d.recoveryCrypto.approve.mockRejectedValue(new RecoveryCheckError('not_listed'));
    await expect(approveOnce(d, identity, keys, detail, new Uint8Array(32))).rejects.toMatchObject({
      fault: 'not_listed',
    });
    expect(d.recoveryRequests.approve).not.toHaveBeenCalled();
  });

  it('names each kind of failure for the screen', () => {
    expect(faultOf(new RecoveryCheckError('self_approval'))).toBe('self_approval');
    expect(faultOf(new CeremonyCheckError('signature_invalid'))).toBe('trust');
    expect(faultOf(new RecoveryRefusedError('ALREADY_DECIDED'))).toBe('refused.ALREADY_DECIDED');
    expect(faultOf(new Error('x'))).toBe('unavailable');
  });
});
