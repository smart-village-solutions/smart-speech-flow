import { cleanup, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { aesKey } from '@/core/crypto/aead';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { fromBuffer, randomBytes } from '@/core/crypto/bytes';
import { notesDigest } from '@/core/crypto/verification';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';
import { AppError } from '@/core/http/AppError';
import type { VerificationRecord } from '@/domain/archive/archive.types';
import type { ReviewRepository } from '@/domain/review/review.repository';
import type { DecisionPost } from '@/domain/review/review.types';
import {
  IDS,
  loadedFixture,
  openedConversation,
} from '@/features/archive/__tests__/archiveFixture';
import { buildTimeline } from '@/features/archive/timeline';
import type { ReviewState } from '@/features/review/openReview';
import { ReadyReview } from '@/features/review/ReadyReview';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
}));

const r = de.admin.review;
const TENANT = 'tenant-kassel';
const VID = '20000000-0000-4000-8000-000000000001';
const archiveCrypto = createWebArchiveCrypto();

async function unlockedKeys(): Promise<UnlockedKeys> {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, [
    'deriveBits',
  ]);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
  return {
    encPub: fromBuffer(await crypto.subtle.exportKey('raw', enc.publicKey)),
    sigPub: fromBuffer(await crypto.subtle.exportKey('raw', sig.publicKey)),
    encPrivate: enc.privateKey,
    sigPrivate: sig.privateKey,
    fingerprint: new Uint8Array(32),
  };
}

async function state(
  status: VerificationRecord['status']
): Promise<Extract<ReviewState, { status: 'ready' }>> {
  const opened = openedConversation();
  const keys = new Map([[IDS.key, await aesKey(randomBytes(32))]]);
  const record: VerificationRecord = {
    verificationId: VID,
    status,
    requestedBy: 'alice',
    requestedAt: 'q',
    reviewerSub: 'rita',
    reviewerName: null,
    reviewerKeyVersion: 1,
    reviewerFingerprint: new Uint8Array(32),
    startedAt: status === 'in_review' ? 's' : null,
    reviewedHeadSeq: status === 'in_review' ? opened.entries[1].seq : null,
    reviewedHead: status === 'in_review' ? opened.entries[1].hash : null,
    permissionSnapshot: status === 'in_review' ? ['ssf.recording.review'] : null,
    decidedAt: null,
    closedAt: null,
    closeReason: null,
    decided: null,
  };
  return {
    status: 'ready',
    review: {
      opened,
      record,
      draft: { overall: null, notes: [] },
      requester: null,
      requesterName: 'Alice Employee',
    },
    ready: {
      status: 'ready',
      opened,
      keys,
      stamps: [],
      signers: new Map(),
      records: [],
      view: buildTimeline(opened, loadedFixture(), keys),
    },
    draft: { findings: new Map(), overall: '' },
  };
}

function render(
  s: Extract<ReviewState, { status: 'ready' }>,
  unlocked: UnlockedKeys,
  reviews: Partial<ReviewRepository>
) {
  const onStarted = vi.fn();
  const onDone = vi.fn();
  renderWithProviders(
    <ReadyReview state={s} unlocked={unlocked} onStarted={onStarted} onDone={onDone} />,
    {
      locale: 'de',
      services: { reviews: reviews as ReviewRepository, archiveCrypto },
    }
  );
  return { onStarted, onDone };
}

describe('ReadyReview (spec §10.7)', { timeout: 30_000 }, () => {
  beforeEach(() =>
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: TENANT, userSub: 'rita' })
  );

  it('starts with the head the reviewer loaded, before any note can be written', async () => {
    const s = await state('awaiting');
    const reviews = { start: vi.fn().mockResolvedValue(s.review.record) };
    const { onStarted } = render(s, await unlockedKeys(), reviews);
    expect(screen.queryByText(r.addFinding)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: r.start }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(reviews.start).toHaveBeenCalledWith(VID, s.ready.opened.entries.at(-1)?.seq);
  });

  it('reloads when the conversation grew since it was opened, and says so', async () => {
    const s = await state('awaiting');
    const reviews = {
      start: vi
        .fn()
        .mockRejectedValue(new AppError('validation', { status: 409, serverCode: 'HEAD_CHANGED' })),
    };
    const { onStarted } = render(s, await unlockedKeys(), reviews);
    expect(screen.getByText(/Alice Employee/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: r.start }));
    expect(await screen.findByRole('alert')).toHaveTextContent(r.error.HEAD_CHANGED);
    expect(onStarted).toHaveBeenCalled();
  });

  it('declines only after the confirmation', async () => {
    const reviews = { decline: vi.fn().mockResolvedValue(undefined) };
    const { onDone } = render(await state('awaiting'), await unlockedKeys(), reviews);
    await userEvent.click(screen.getByRole('button', { name: r.decline }));
    expect(reviews.decline).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: r.declineConfirm }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('declined'));
  });

  it('takes notes only up to the reviewed head and saves them encrypted per entry', async () => {
    const reviews = { saveDraft: vi.fn().mockResolvedValue(undefined) };
    render(await state('in_review'), await unlockedKeys(), reviews);
    expect(screen.getAllByText(r.afterHead).length).toBeGreaterThan(0);
    await userEvent.click(screen.getAllByRole('button', { name: r.addFinding })[1]);
    await userEvent.type(screen.getByLabelText(r.findingText), 'Satz fehlt');
    expect(screen.getByText(r.unsaved)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: r.save }));
    await waitFor(() => expect(screen.getByText(r.saved)).toBeInTheDocument());
    const [, draft] = reviews.saveDraft.mock.calls[0];
    expect(draft.notes.map((n: { entryId: string }) => n.entryId)).toEqual([IDS.message]);
    expect(draft.overall).toBeNull();
  });

  it('allows at most ten findings per entry', async () => {
    render(await state('in_review'), await unlockedKeys(), {});
    const add = () => screen.getAllByRole('button', { name: r.addFinding })[0];
    for (let i = 0; i < 10; i += 1) await userEvent.click(add());
    expect(screen.getAllByLabelText(r.findingText)).toHaveLength(10);
    expect(screen.getAllByRole('button', { name: r.addFinding })).toHaveLength(1);
  });

  it('signs over the digest of exactly the notes it posts and the snapshot', async () => {
    const unlocked = await unlockedKeys();
    const s = await state('in_review');
    const posted: DecisionPost[] = [];
    const reviews = {
      decide: vi
        .fn()
        .mockImplementation((_id, post) => (posted.push(post), Promise.resolve(s.review.record))),
      saveDraft: vi.fn().mockResolvedValue(undefined),
    };
    const { onDone } = render(s, unlocked, reviews);
    await userEvent.click(screen.getAllByRole('button', { name: r.addFinding })[1]);
    await userEvent.type(screen.getByLabelText(r.findingText), 'Auslassung');
    await userEvent.click(screen.getByRole('button', { name: r.decide }));
    await userEvent.click(screen.getByLabelText(r.decision.not_approved));
    await userEvent.click(screen.getByRole('button', { name: r.decision.submit }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('decided'));
    const [post] = posted;
    const fields = {
      tenantId: TENANT,
      verificationId: VID,
      conversationId: IDS.conversation,
      reviewedHead: s.review.record.reviewedHead!,
      outcome: 'not_approved',
      notesDigest: await notesDigest(post.overall, post.notes),
      snapshot: ['ssf.recording.review'],
    };
    expect(post.notes).toHaveLength(1);
    cleanup(); // the screen closes after a decision: nothing is left to save into
    // A save on close seals first, so give it time to reach the repository before asserting none did.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(reviews.saveDraft).not.toHaveBeenCalled();
    expect(await archiveCrypto.verifyVerification(unlocked.sigPub, post.signature, fields)).toBe(
      true
    );
  });

  it('re-takes a changed permission snapshot once and signs anew', async () => {
    const unlocked = await unlockedKeys();
    const s = await state('in_review');
    const sworn = {
      ...s.review.record,
      permissionSnapshot: ['ssf.recording.review', 'ssf.recording.review.sworn'],
    };
    const posted: DecisionPost[] = [];
    const reviews = {
      start: vi.fn().mockResolvedValue(sworn),
      decide: vi
        .fn()
        .mockImplementationOnce(
          (_id, post) => (
            posted.push(post),
            Promise.reject(
              new AppError('validation', { status: 409, serverCode: 'PERMISSIONS_CHANGED' })
            )
          )
        )
        .mockImplementationOnce((_id, post) => (posted.push(post), Promise.resolve(sworn))),
    };
    const { onDone } = render(s, unlocked, reviews);
    await userEvent.click(screen.getByRole('button', { name: r.decide }));
    await userEvent.click(screen.getByLabelText(r.decision.approved));
    await userEvent.click(screen.getByRole('button', { name: r.decision.submit }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('decided'));
    const fields = (snapshot: string[]) => ({
      tenantId: TENANT,
      verificationId: VID,
      conversationId: IDS.conversation,
      reviewedHead: s.review.record.reviewedHead!,
      outcome: 'approved',
      notesDigest: new Uint8Array(0),
      snapshot,
    });
    const digest = await notesDigest(null, []);
    expect(
      await archiveCrypto.verifyVerification(unlocked.sigPub, posted[1].signature, {
        ...fields(sworn.permissionSnapshot),
        notesDigest: digest,
      })
    ).toBe(true);
    expect(
      await archiveCrypto.verifyVerification(unlocked.sigPub, posted[0].signature, {
        ...fields(['ssf.recording.review']),
        notesDigest: digest,
      })
    ).toBe(true);
  });

  it('says why a decision was refused', async () => {
    const s = await state('in_review');
    const reviews = {
      decide: vi
        .fn()
        .mockRejectedValue(
          new AppError('validation', { status: 409, serverCode: 'NOT_A_REVIEWER' })
        ),
    };
    render(s, await unlockedKeys(), reviews);
    await userEvent.click(screen.getByRole('button', { name: r.decide }));
    await userEvent.click(screen.getByLabelText(r.decision.approved));
    await userEvent.click(screen.getByRole('button', { name: r.decision.submit }));
    expect(await screen.findByRole('alert')).toHaveTextContent(r.error.NOT_A_REVIEWER);
  });
});
