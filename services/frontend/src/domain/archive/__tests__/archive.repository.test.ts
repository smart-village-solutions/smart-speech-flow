import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { fromBase64Url } from '@/core/crypto/bytes';
import { createHttpClient } from '@/core/http/client';
import {
  AmendmentNotStoredError,
  ObjectNotStoredError,
  createArchiveRepository,
} from '@/domain/archive/archive.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const URL = `${BASE}/api/admin/recording/archive`;
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const ENTRY = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';

function repository() {
  return createArchiveRepository(
    createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de')
  );
}

const coded = (status: number, code: string) =>
  HttpResponse.json({ detail: { error_code: code, message: 'x' } }, { status });

describe('archive repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('pages the list by the last row’s start and ID', async () => {
    const seen: string[] = [];
    server.use(
      http.get(URL, ({ request }) => {
        seen.push(new globalThis.URL(request.url).search);
        return HttpResponse.json({ conversations: [] });
      })
    );
    await repository().list();
    await repository().list({ startedBefore: '2026-10-29T10:00:00+00:00', beforeId: ID });
    expect(seen[0]).toBe('');
    const params = new URLSearchParams(seen[1]);
    expect(params.get('before_id')).toBe(ID);
    // The offset's `+` must survive the query string.
    expect(params.get('started_before')).toBe('2026-10-29T10:00:00+00:00');
  });

  it('fetches ciphertext as bytes, and says when an object is not stored yet', async () => {
    server.use(
      http.get(`${URL}/${ID}/objects/${ENTRY}/record.json`, () =>
        HttpResponse.arrayBuffer(new Uint8Array([1, 2, 3]).buffer)
      ),
      http.get(`${URL}/${ID}/objects/${ENTRY}/original.wav`, () => coded(404, 'OBJECT_NOT_STORED'))
    );
    expect(Array.from(await repository().object(ID, ENTRY, 'record.json'))).toEqual([1, 2, 3]);
    await expect(repository().object(ID, ENTRY, 'original.wav')).rejects.toBeInstanceOf(
      ObjectNotStoredError
    );
  });

  it('posts an amendment as base64url, and tells a committed but unstored one apart', async () => {
    let body: Record<string, string> = {};
    server.use(
      http.post(`${URL}/${ID}/amendments`, async ({ request }) => {
        body = (await request.json()) as Record<string, string>;
        return body.key_id === 'fail'
          ? coded(503, 'ARCHIVE_WRITE_FAILED')
          : HttpResponse.json({ entry_id: ENTRY, seq: 7 }, { status: 201 });
      })
    );
    const ciphertext = new Uint8Array([1, 250, 251]);
    expect(await repository().amend(ID, { entryId: ENTRY, keyId: ID, ciphertext })).toEqual({
      entryId: ENTRY,
      seq: 7,
    });
    expect(Array.from(fromBase64Url(body.ciphertext))).toEqual([1, 250, 251]);
    expect(body.ciphertext).not.toMatch(/[+/=]/);
    await expect(
      repository().amend(ID, { entryId: ENTRY, keyId: 'fail', ciphertext })
    ).rejects.toBeInstanceOf(AmendmentNotStoredError);
  });

  it('reports an integrity failure by stage', async () => {
    let stage = '';
    server.use(
      http.post(`${URL}/${ID}/integrity-failures`, async ({ request }) => {
        stage = ((await request.json()) as { stage: string }).stage;
        return new HttpResponse(null, { status: 204 });
      })
    );
    await repository().reportIntegrity(ID, 'chain');
    expect(stage).toBe('chain');
  });
});
