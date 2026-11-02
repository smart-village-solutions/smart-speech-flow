import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { toBase64Url } from '@/core/crypto/bytes';
import { createHttpClient } from '@/core/http/client';
import { createArchiveRepository } from '@/domain/archive/archive.repository';
import { recordBody } from '@/domain/archive/__tests__/verificationFixture';
import { createReviewRepository } from '@/domain/review/review.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const REVIEWS = `${BASE}/api/admin/recording/reviews`;
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const ENTRY = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';
const client = () => createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de');
const b = (n: number, length: number) => toBase64Url(new Uint8Array(length).fill(n));

const conversation = {
  verifications: [],
  conversation: {
    conversation_id: ID,
    employee_sub: 'alice',
    legal_basis: 'consent',
    started_at: 's',
    ended_at: 'e',
    retention_until: 'r',
    legal_hold: false,
    incomplete: false,
    verification: { status: 'not_verified', approved: 0, not_approved: 0 },
  },
  windows: [],
  entries: [],
  stamps: [],
  keys: [],
};

describe('review repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads the inbox and opens a review with its draft and requester', async () => {
    server.use(
      http.get(REVIEWS, () =>
        HttpResponse.json({
          reviews: [
            {
              verification_id: ID,
              status: 'in_review',
              requested_at: 'q',
              requested_by: 'alice',
              started_at: 's',
              ended_at: null,
              messages: 2,
              openable: true,
              requested_by_name: 'Alice Employee',
            },
          ],
        })
      ),
      http.get(`${REVIEWS}/${ID}`, () =>
        HttpResponse.json({
          ...conversation,
          review: {
            record: recordBody({ status: 'in_review' }),
            draft: {
              overall: b(1, 30),
              notes: [{ entry_id: ENTRY, key_id: ID, ciphertext: b(2, 30) }],
            },
            requester: {
              sub: 'alice',
              key_version: 1,
              fingerprint: b(1, 32),
              enc_pub: b(4, 65),
              sig_pub: b(5, 65),
            },
            requester_name: 'Alice Employee',
          },
        })
      )
    );
    const repo = createReviewRepository(client());
    const [row] = await repo.inbox();
    const opened = await repo.open(ID);
    expect(row).toMatchObject({ status: 'in_review', openable: true, messages: 2 });
    expect(opened.record.status).toBe('in_review');
    expect(opened.draft.notes[0].entryId).toBe(ENTRY);
    expect(opened.requester?.sub).toBe('alice');
    expect([row.requestedByName, opened.requesterName]).toEqual([
      'Alice Employee',
      'Alice Employee',
    ]);
    expect(opened.opened.conversation.conversationId).toBe(ID);
  });

  it('starts, saves a draft, declines and decides with encoded bodies', async () => {
    const bodies: Record<string, unknown> = {};
    server.use(
      http.post(`${REVIEWS}/${ID}/start`, async ({ request }) => {
        bodies.start = await request.json();
        return HttpResponse.json(recordBody({ status: 'in_review' }));
      }),
      http.put(`${REVIEWS}/${ID}/draft`, async ({ request }) => {
        bodies.draft = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
      http.post(`${REVIEWS}/${ID}/decline`, () => new HttpResponse(null, { status: 204 })),
      http.post(`${REVIEWS}/${ID}/decision`, async ({ request }) => {
        bodies.decision = await request.json();
        return HttpResponse.json(
          recordBody({
            status: 'approved',
            outcome: 'approved',
            signature: b(2, 64),
            reviewed_head: b(3, 32),
            permission_snapshot: [],
          })
        );
      })
    );
    const repo = createReviewRepository(client());
    const note = { entryId: ENTRY, keyId: ID, ciphertext: new Uint8Array(30).fill(2) };
    expect((await repo.start(ID, 4)).status).toBe('in_review');
    await repo.saveDraft(ID, { overall: null, notes: [note] });
    await repo.decline(ID);
    const decided = await repo.decide(ID, {
      overall: null,
      notes: [note],
      outcome: 'approved',
      signature: new Uint8Array(64).fill(2),
    });
    expect(bodies.start).toEqual({ expected_head_seq: 4 });
    expect(bodies.draft).toEqual({
      overall: null,
      notes: [{ entry_id: ENTRY, key_id: ID, ciphertext: b(2, 30) }],
    });
    expect(bodies.decision).toMatchObject({ outcome: 'approved', signature: b(2, 64) });
    expect(decided.decided?.outcome).toBe('approved');
  });

  it('lists reviewers and assigns through the archive routes', async () => {
    let posted: unknown;
    server.use(
      http.get(`${BASE}/api/admin/recording/archive/${ID}/reviewers`, () =>
        HttpResponse.json({ reviewers: [] })
      ),
      http.post(`${BASE}/api/admin/recording/archive/${ID}/verifications`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(recordBody(), { status: 201 });
      })
    );
    const archive = createArchiveRepository(client());
    expect(await archive.reviewers(ID)).toEqual([]);
    const record = await archive.assign(ID, {
      keyVersion: 1,
      reviewerSub: 'rita',
      reviewerKeyVersion: 2,
      wraps: [{ keyId: ID, blob: '{}', signature: new Uint8Array(64).fill(7) }],
    });
    expect(posted).toEqual({
      key_version: 1,
      reviewer_sub: 'rita',
      reviewer_key_version: 2,
      wraps: [{ key_id: ID, blob: '{}', signature: b(7, 64) }],
    });
    expect(record.status).toBe('awaiting');
  });
});
