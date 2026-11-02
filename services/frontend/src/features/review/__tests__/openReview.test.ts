import { beforeEach, describe, expect, it, vi } from 'vitest';
import { aesKey } from '@/core/crypto/aead';
import { fromBuffer, randomBytes } from '@/core/crypto/bytes';
import { fingerprint } from '@/core/crypto/transcript';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';
import type { ArchiveRepository } from '@/domain/archive/archive.repository';
import type { VerificationRecord } from '@/domain/archive/archive.types';
import { noteJson, overallJson, parseFindings, parseOverall } from '@/domain/review/findings';
import type { ReviewRepository } from '@/domain/review/review.repository';
import type { ReviewOpened } from '@/domain/review/review.types';
import { finishOpening } from '@/features/archive/openConversation';
import { verifyConversation } from '@/features/archive/verifyConversation';
import { noteAddress, openReview } from '@/features/review/openReview';
import { sealNotes } from '@/features/review/sealNotes';
import { IDS, openedConversation } from '@/features/archive/__tests__/archiveFixture';

vi.mock('@/features/archive/verifyConversation', () => ({ verifyConversation: vi.fn() }));
vi.mock('@/features/archive/openConversation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/archive/openConversation')>()),
  finishOpening: vi.fn(),
}));

const TENANT = 'tenant-kassel';
const VID = '20000000-0000-4000-8000-000000000001';
const archiveCrypto = createWebArchiveCrypto();

async function publicKeys(sub: string) {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, [
    'deriveBits',
  ]);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
    'sign',
    'verify',
  ]);
  const encPub = fromBuffer(await crypto.subtle.exportKey('raw', enc.publicKey));
  const sigPub = fromBuffer(await crypto.subtle.exportKey('raw', sig.publicKey));
  return {
    sub,
    keyVersion: 1,
    encPub,
    sigPub,
    fingerprint: await fingerprint(TENANT, sub, encPub, sigPub),
  };
}

function record(changes: Partial<VerificationRecord> = {}): VerificationRecord {
  const opened = openedConversation();
  return {
    verificationId: VID,
    status: 'in_review',
    requestedBy: 'alice',
    requestedAt: 'q',
    reviewerSub: 'rita',
    reviewerName: null,
    reviewerKeyVersion: 1,
    reviewerFingerprint: new Uint8Array(32),
    startedAt: 's',
    reviewedHeadSeq: opened.entries[1].seq,
    reviewedHead: opened.entries[1].hash,
    permissionSnapshot: ['ssf.recording.review'],
    decidedAt: null,
    closedAt: null,
    closeReason: null,
    decided: null,
    ...changes,
  };
}

async function deps(review: ReviewOpened) {
  const reviews = { open: vi.fn().mockResolvedValue(review) } as unknown as ReviewRepository;
  const archive = {
    trust: vi.fn().mockResolvedValue({}),
    reportIntegrity: vi.fn().mockResolvedValue(undefined),
  } as unknown as ArchiveRepository;
  return {
    reviews,
    archive,
    archiveCrypto,
    ceremonyCrypto: {} as never,
    identity: { tenantId: TENANT, userSub: 'rita' },
  };
}

describe('openReview (spec §10.7)', { timeout: 30_000 }, () => {
  const ck = aesKey(randomBytes(32));
  const keys = async () => new Map([[IDS.key, await ck]]);

  beforeEach(async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: await keys(),
      stamps: [],
      signers: new Map(),
    });
    vi.mocked(finishOpening).mockImplementation(async (_deps, opened) => ({
      status: 'ready',
      opened,
      keys: await keys(),
      stamps: [],
      signers: new Map(),
      records: [],
      view: {
        entries: [],
        gaps: [],
        unattached: [],
        header: { guestName: null, enteredBy: null, languages: [] },
      },
    }));
  });

  it('accepts the assigner as wrap signer only after their fingerprint matches, and opens the draft', async () => {
    const requester = await publicKeys('alice');
    const opened = openedConversation();
    const r = record();
    const draft = await sealNotes({
      crypto: archiveCrypto,
      tenantId: TENANT,
      review: { opened, record: r, draft: { overall: null, notes: [] }, requester },
      keys: await keys(),
      findings: new Map([
        [IDS.message, [{ category: 'omission' as const, text: 'fehlt', suggestion: '' }]],
        [IDS.consent, []],
      ]),
      overall: 'Insgesamt gut.',
    });
    expect(draft.notes.map((note) => note.entryId)).toEqual([IDS.message]);

    const d = await deps({ opened, record: r, draft, requester });
    const state = await openReview(d, VID, {} as never);

    expect(verifyConversation).toHaveBeenCalledWith(
      expect.objectContaining({ wrapSigners: new Map([['alice', requester.sigPub]]) })
    );
    expect(state.status).toBe('ready');
    if (state.status !== 'ready') return;
    expect(state.draft.findings.get(IDS.message)?.[0].text).toBe('fehlt');
    expect(state.draft.overall).toBe('Insgesamt gut.');
  });

  it('refuses an assigner whose keys do not match the fingerprint served', async () => {
    const requester = { ...(await publicKeys('alice')), fingerprint: new Uint8Array(32) };
    const d = await deps({
      opened: openedConversation(),
      record: record(),
      draft: { overall: null, notes: [] },
      requester,
    });
    expect(await openReview(d, VID, {} as never)).toEqual({ status: 'broken', stage: 'wrap' });
    expect(verifyConversation).not.toHaveBeenCalled();
    expect(d.archive.reportIntegrity).toHaveBeenCalledWith(IDS.conversation, 'wrap');
  });

  it('refuses a record for someone else or a requester other than the record names', async () => {
    const requester = await publicKeys('mallory');
    const other = await deps({
      opened: openedConversation(),
      record: record({ reviewerSub: 'ralf' }),
      draft: { overall: null, notes: [] },
      requester,
    });
    expect(await openReview(other, VID, {} as never)).toEqual({ status: 'broken', stage: 'chain' });
    const wrongRequester = await deps({
      opened: openedConversation(),
      record: record(),
      draft: { overall: null, notes: [] },
      requester,
    });
    expect(await openReview(wrongRequester, VID, {} as never)).toEqual({
      status: 'broken',
      stage: 'wrap',
    });
  });

  it('seals every note under its own entry key and binds the record and entry', async () => {
    const opened = openedConversation();
    const r = record();
    const sealed = await sealNotes({
      crypto: archiveCrypto,
      tenantId: TENANT,
      review: { opened, record: r, draft: { overall: null, notes: [] }, requester: null },
      keys: await keys(),
      findings: new Map([
        [
          IDS.message,
          [{ category: 'asr_error' as const, text: 'x', suggestion: 'y', id: 'ui-only' } as never],
        ],
      ]),
      overall: '   ',
    });
    expect(sealed.overall).toBeNull();
    const [note] = sealed.notes;
    const plain = await archiveCrypto.openNote(
      await ck,
      noteAddress(TENANT, r, IDS.conversation, 'note', IDS.message, IDS.key),
      note.ciphertext
    );
    expect(parseFindings(plain, VID, IDS.message)).toEqual([
      { category: 'asr_error', text: 'x', suggestion: 'y' },
    ]);
    expect(() => parseFindings(plain, VID, IDS.consent)).toThrow();
    expect(new TextDecoder().decode(plain)).not.toContain('ui-only');
    expect(parseOverall(overallJson(VID, 'a'), VID)).toBe('a');
    expect(() => parseOverall(noteJson(VID, IDS.message, []), 'other')).toThrow();
  });
});

describe('sealNotes: empty findings (M3)', { timeout: 30_000 }, () => {
  it('never seals a finding without text, so no reader breaks on it', async () => {
    const opened = openedConversation();
    const sealed = await sealNotes({
      crypto: archiveCrypto,
      tenantId: TENANT,
      review: {
        opened,
        record: record(),
        draft: { overall: null, notes: [] },
        requester: null,
        requesterName: null,
      },
      keys: new Map([[IDS.key, await aesKey(randomBytes(32))]]),
      findings: new Map([
        [IDS.message, [{ category: 'omission' as const, text: '  ', suggestion: '' }]],
        [
          IDS.consent,
          [
            { category: 'omission' as const, text: '', suggestion: 'x' },
            { category: 'asr_error' as const, text: 'echt', suggestion: '' },
          ],
        ],
      ]),
      overall: '',
    });
    expect(sealed.notes.map((note) => note.entryId)).toEqual([IDS.consent]);
  });
});
