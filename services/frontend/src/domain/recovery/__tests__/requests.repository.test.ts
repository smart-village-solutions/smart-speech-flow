import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { AppError } from '@/core/http/AppError';
import {
  RecoveryRefusedError,
  createRecoveryRequestsRepository,
} from '@/domain/recovery/requests.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const URL = `${BASE}/api/admin/recording/recovery`;
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const KEY = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';

function repository() {
  return createRecoveryRequestsRepository(
    createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de')
  );
}

const coded = (status: number, code: string) =>
  HttpResponse.json({ detail: { error_code: code, message: 'x' } }, { status });

describe('recovery requests repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('files a request with its signature and reads back the scope', async () => {
    let sent: unknown;
    server.use(
      http.post(`${URL}/requests`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          { request_id: ID, scope: [{ conversation_id: ID, key_id: KEY }] },
          { status: 201 }
        );
      })
    );
    const scope = await repository().file({
      requestId: ID,
      kind: 'key_recovery',
      reason: 'why',
      conversationIds: [ID],
      signature: new Uint8Array(64),
    });
    expect(sent).toEqual({
      request_id: ID,
      kind: 'key_recovery',
      reason: 'why',
      conversation_ids: [ID],
      signature: 'A'.repeat(86),
    });
    expect(scope).toEqual([{ conversationId: ID, keyId: KEY }]);
  });

  it('posts approvals, wraps and rejections in the gateway shape', async () => {
    const bodies: Record<string, unknown> = {};
    const record =
      (name: string) =>
      async ({ request }: { request: Request }) => {
        bodies[name] = await request.json();
        return name === 'wraps'
          ? HttpResponse.json({ dropped: [KEY] })
          : new HttpResponse(null, { status: 204 });
      };
    server.use(
      http.post(`${URL}/approvals/${ID}`, record('approve')),
      http.post(`${URL}/requests/${ID}/wraps`, record('wraps')),
      http.post(`${URL}/requests/${ID}/rejections`, record('reject'))
    );
    const repo = repository();
    await repo.approve(ID, new Map([[KEY, '{"p":1}']]), new Uint8Array(64));
    const dropped = await repo.storeWraps(ID, [
      { conversationId: ID, keyId: KEY, blob: '{}', signature: new Uint8Array(64) },
    ]);
    await repo.reject(ID, { holderIndex: 2, attempt: 1, fault: 'proof_invalid' });
    expect(bodies.approve).toEqual({ partials: { [KEY]: '{"p":1}' }, signature: 'A'.repeat(86) });
    expect(bodies.wraps).toEqual({
      wraps: [{ conversation_id: ID, key_id: KEY, blob: '{}', signature: 'A'.repeat(86) }],
    });
    expect(bodies.reject).toEqual({ holder_index: 2, attempt: 1, fault: 'proof_invalid' });
    expect(dropped).toEqual([KEY]);
  });

  it('turns a coded refusal into RecoveryRefusedError and leaves outages as they are', async () => {
    server.use(
      http.post(`${URL}/approvals/${ID}/decline`, () => coded(409, 'ALREADY_DECIDED')),
      http.post(`${URL}/requests/${ID}/cancel`, () => coded(503, 'RECORDING_UNAVAILABLE'))
    );
    await expect(repository().decline(ID, 'no')).rejects.toMatchObject({
      name: 'RecoveryRefusedError',
      code: 'ALREADY_DECIDED',
    });
    const outage = repository().cancel(ID);
    await expect(outage).rejects.toBeInstanceOf(AppError);
    await expect(outage).rejects.not.toBeInstanceOf(RecoveryRefusedError);
  });

  it('asks for candidates by employee and range', async () => {
    let search = '';
    server.use(
      http.get(`${URL}/candidates`, ({ request }) => {
        search = new globalThis.URL(request.url).search;
        return HttpResponse.json({ conversations: [] });
      })
    );
    await repository().candidates('alice', '2026-10-01T00:00:00Z', '2026-10-31T00:00:00Z');
    const params = new URLSearchParams(search);
    expect([params.get('employee'), params.get('from'), params.get('to')]).toEqual([
      'alice',
      '2026-10-01T00:00:00Z',
      '2026-10-31T00:00:00Z',
    ]);
  });

  it('reads the own batch, lists by kind and names an unrecoverable key', async () => {
    let listed = '';
    let reported: unknown;
    server.use(
      http.get(`${URL}/own/candidates`, () =>
        HttpResponse.json({ conversations: [], remaining: { conversations: 2, keys: 4 } })
      ),
      http.get(`${URL}/requests`, ({ request }) => {
        listed = new globalThis.URL(request.url).search;
        return HttpResponse.json({ requests: [] });
      }),
      http.post(`${URL}/requests/${ID}/integrity-failures`, async ({ request }) => {
        reported = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(`${URL}/approvals`, () => HttpResponse.json({ requests: [], share_stale: true }))
    );
    const repo = repository();
    expect((await repo.ownCandidates()).remaining).toEqual({ conversations: 2, keys: 4 });
    await repo.requests('key_recovery');
    await repo.reportIntegrity(ID, 'wrap_damaged', KEY);
    expect(new URLSearchParams(listed).get('kind')).toBe('key_recovery');
    expect(reported).toEqual({ stage: 'wrap_damaged', key_id: KEY });
    expect((await repo.approvals()).shareStale).toBe(true);
  });
});
