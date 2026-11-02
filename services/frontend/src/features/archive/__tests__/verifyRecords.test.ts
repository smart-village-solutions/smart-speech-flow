import { beforeEach, describe, expect, it, vi } from 'vitest';
import { aesKey } from '@/core/crypto/aead';
import { fromBuffer, randomBytes } from '@/core/crypto/bytes';
import { fingerprint } from '@/core/crypto/transcript';
import { readTimestamp } from '@/core/crypto/tst-info';
import { notesDigest } from '@/core/crypto/verification';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';
import type {
  DecidedFacts,
  OpenedConversation,
  VerificationRecord,
} from '@/domain/archive/archive.types';
import { noteJson, overallJson } from '@/domain/review/findings';
import { verifyRecords } from '@/features/archive/verifyRecords';
import { IDS, openedConversation } from './archiveFixture';

vi.mock('@/core/crypto/tst-info', () => ({ readTimestamp: vi.fn() }));

const TENANT = 'tenant-kassel';
const VID = '20000000-0000-4000-8000-000000000001';
const archiveCrypto = createWebArchiveCrypto();
const finding = { category: 'omission' as const, text: 'Satz fehlt', suggestion: '' };

async function reviewerKeys() {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, [
    'deriveBits',
  ]);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
  const encPub = fromBuffer(await crypto.subtle.exportKey('raw', enc.publicKey));
  const sigPub = fromBuffer(await crypto.subtle.exportKey('raw', sig.publicKey));
  return {
    encPub,
    sigPub,
    encPrivate: enc.privateKey,
    sigPrivate: sig.privateKey,
    fingerprint: await fingerprint(TENANT, 'rita', encPub, sigPub),
  };
}

interface Setup {
  opened: OpenedConversation;
  keys: Map<string, CryptoKey>;
  record: VerificationRecord;
}

/** A decided record on entry 2's head, signed by a real reviewer key (A.3a). */
async function setup(
  tamper: (draft: {
    noteEntry: string;
    outcome: 'approved' | 'not_approved';
    head: number;
  }) => void = () => undefined
): Promise<Setup> {
  const opened = openedConversation();
  const ck = await aesKey(randomBytes(32));
  const keys = new Map([[IDS.key, ck]]);
  const rita = await reviewerKeys();
  const draft = {
    noteEntry: IDS.message,
    outcome: 'approved' as 'approved' | 'not_approved',
    head: 1,
  };
  tamper(draft);
  const head = opened.entries[1];
  const address = (part: 'note' | 'overall', entryId: string) => ({
    tenantId: TENANT,
    conversationId: IDS.conversation,
    verificationId: VID,
    part,
    entryId,
    keyId: IDS.key,
  });
  const note = {
    entryId: IDS.message,
    keyId: IDS.key,
    ciphertext: await archiveCrypto.sealNote(
      ck,
      address('note', IDS.message),
      noteJson(VID, draft.noteEntry, [finding])
    ),
  };
  const overall = await archiveCrypto.sealNote(
    ck,
    address('overall', head.entryId),
    overallJson(VID, 'Gut.')
  );
  const snapshot = ['ssf.recording.review'];
  const signature = await archiveCrypto.signVerification(rita, {
    tenantId: TENANT,
    verificationId: VID,
    conversationId: IDS.conversation,
    reviewedHead: head.hash,
    outcome: draft.outcome,
    notesDigest: await notesDigest(overall, [note]),
    snapshot,
  });
  const decided: DecidedFacts = {
    outcome: 'approved',
    overallNote: overall,
    notes: [note],
    signature,
    reviewerKey: { keyVersion: 1, encPub: rita.encPub, sigPub: rita.sigPub },
    tsaToken: null,
  };
  const record: VerificationRecord = {
    verificationId: VID,
    status: 'approved',
    requestedBy: 'alice',
    requestedAt: 'q',
    reviewerSub: 'rita',
    reviewerName: 'Rita',
    reviewerKeyVersion: 1,
    reviewerFingerprint: rita.fingerprint,
    startedAt: 's',
    reviewedHeadSeq: head.seq,
    reviewedHead: opened.entries[draft.head].hash,
    permissionSnapshot: snapshot,
    decidedAt: 'd',
    closedAt: null,
    closeReason: null,
    decided,
  };
  return { opened: { ...opened, verifications: [record] }, keys, record };
}

const run = (s: Setup, keys: ReadonlyMap<string, CryptoKey> = s.keys) =>
  verifyRecords({ tenantId: TENANT, opened: s.opened, keys, archiveCrypto });

function withRecord(
  s: Setup,
  change: Partial<VerificationRecord>,
  decided: Partial<DecidedFacts> = {}
): Setup {
  const record = { ...s.record, ...change, decided: { ...s.record.decided!, ...decided } };
  return { ...s, opened: { ...s.opened, verifications: [record] }, record };
}

describe('verifyRecords (spec §10.7, results)', { timeout: 30_000 }, () => {
  beforeEach(() => vi.mocked(readTimestamp).mockReset());

  it('verifies a decided record and opens its findings and overall note', async () => {
    const s = await setup();
    const [view] = await run(s);
    expect(view.state).toBe('verified');
    expect(view.findings.get(IDS.message)).toEqual([expect.objectContaining(finding)]);
    expect(view.overall).toBe('Gut.');
    expect(view.entriesAfter).toBe(s.opened.entries.length - 2); // reviewed up to the second entry
  });

  it.each([
    [
      'another reviewer fingerprint',
      (s: Setup) => withRecord(s, { reviewerFingerprint: new Uint8Array(32) }),
    ],
    ['a changed outcome', (s: Setup) => withRecord(s, {}, { outcome: 'not_approved' })],
    [
      'a changed snapshot',
      (s: Setup) => withRecord(s, { permissionSnapshot: ['ssf.recording.review.sworn'] }),
    ],
    [
      'a head outside the chain',
      (s: Setup) => withRecord(s, { reviewedHead: new Uint8Array(32).fill(99) }),
    ],
    ['a dropped note', (s: Setup) => withRecord(s, {}, { notes: [] })],
    ['no reviewer key', (s: Setup) => withRecord(s, {}, { reviewerKey: null })],
  ])('marks %s as broken and shows nothing', async (_name, change) => {
    const [view] = await run(change(await setup()));
    expect(view.state).toBe('broken');
    expect(view.findings.size).toBe(0);
    expect(view.overall).toBeNull();
  });

  it('refuses a note that names another entry, even with a valid signature', async () => {
    const [view] = await run(await setup((draft) => (draft.noteEntry = IDS.consent)));
    expect(view.state).toBe('broken');
  });

  it('notes a key the reader lacks without breaking the record', async () => {
    const [view] = await run(await setup(), new Map());
    expect(view.state).toBe('verified');
    expect(view.missingKeys).toBe(true);
    expect(view.findings.size).toBe(0);
  });

  it('accepts a stamp naming the decision and refuses one naming anything else', async () => {
    const base = await setup();
    const stamped = withRecord(base, {}, { tsaToken: new Uint8Array([1]) });
    vi.mocked(readTimestamp).mockReturnValue({ imprint: new Uint8Array(32), genTime: 'T' });
    expect((await run(stamped))[0].state).toBe('broken');
    const { decisionImprint, verificationFields } = await import('@/core/crypto/verification');
    const { signedDigest } = await import('@/core/crypto/signatures');
    const { TAGS } = await import('@/core/crypto/tags');
    const fields = verificationFields({
      tenantId: TENANT,
      verificationId: VID,
      conversationId: IDS.conversation,
      reviewedHead: base.record.reviewedHead!,
      outcome: 'approved',
      notesDigest: await notesDigest(base.record.decided!.overallNote, base.record.decided!.notes),
      snapshot: ['ssf.recording.review'],
    });
    const imprint = await decisionImprint(
      await signedDigest(TAGS.verificationSig, fields),
      base.record.decided!.signature
    );
    vi.mocked(readTimestamp).mockReturnValue({ imprint, genTime: 'T' });
    const [view] = await run(stamped);
    expect([view.state, view.stampTime]).toEqual(['verified', 'T']);
  });

  it('keeps open and closed records apart from decided ones', async () => {
    const base = await setup();
    const open = withRecord(base, { status: 'awaiting' });
    const views = await run({
      ...open,
      opened: {
        ...open.opened,
        verifications: [
          { ...open.record, decided: null },
          { ...open.record, status: 'withdrawn', decided: null },
        ],
      },
    });
    expect(views.map((v) => v.state)).toEqual(['open', 'closed']);
  });
});

describe('verifyRecords: the reviewed head', { timeout: 30_000 }, () => {
  it('refuses a validly signed decision on a head outside the chain', async () => {
    const opened = openedConversation();
    const rita = await reviewerKeys();
    const ghost = new Uint8Array(32).fill(77);
    const snapshot = ['ssf.recording.review'];
    const digest = await notesDigest(null, []);
    const signature = await archiveCrypto.signVerification(rita, {
      tenantId: TENANT,
      verificationId: VID,
      conversationId: IDS.conversation,
      reviewedHead: ghost,
      outcome: 'approved',
      notesDigest: digest,
      snapshot,
    });
    const record: VerificationRecord = {
      verificationId: VID,
      status: 'approved',
      requestedBy: 'alice',
      requestedAt: 'q',
      reviewerSub: 'rita',
      reviewerName: null,
      reviewerKeyVersion: 1,
      reviewerFingerprint: rita.fingerprint,
      startedAt: 's',
      reviewedHeadSeq: 2,
      reviewedHead: ghost,
      permissionSnapshot: snapshot,
      decidedAt: 'd',
      closedAt: null,
      closeReason: null,
      decided: {
        outcome: 'approved',
        overallNote: null,
        notes: [],
        signature,
        reviewerKey: { keyVersion: 1, encPub: rita.encPub, sigPub: rita.sigPub },
        tsaToken: null,
      },
    };
    const [view] = await verifyRecords({
      tenantId: TENANT,
      opened: { ...opened, verifications: [record] },
      keys: new Map(),
      archiveCrypto,
    });
    expect(view.state).toBe('broken');
  });
});

describe(
  'verifyRecords: a decided status needs its signed outcome (M1)',
  { timeout: 30_000 },
  () => {
    it.each([
      ['a decided status with no decision', (s: Setup) => ({ ...s.record, decided: null })],
      [
        'a status that differs from the signed outcome',
        (s: Setup) => ({ ...s.record, status: 'not_approved' as const }),
      ],
    ])('marks %s as broken', async (_name, change) => {
      const s = await setup();
      const record = change(s);
      const [view] = await verifyRecords({
        tenantId: TENANT,
        opened: { ...s.opened, verifications: [record] },
        keys: s.keys,
        archiveCrypto,
      });
      expect(view.state).toBe('broken');
    });
  }
);
