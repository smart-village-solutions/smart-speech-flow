import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { toBase64Url } from '@/core/crypto/bytes';
import { publicPoint } from '@/core/crypto/curve';
import { createHttpClient } from '@/core/http/client';
import { createRecordingKeysRepository } from '@/domain/recording/recording.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const fingerprint = toBase64Url(new Uint8Array(32).fill(7));
const display = '0707 0707 0707 0707 0707 0707 0707 0707 0707 0707';

function repository() {
  return createRecordingKeysRepository(createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de'));
}

describe('recording keys repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads the own key', async () => {
    server.use(
      http.get(`${BASE}/api/admin/recording/keys/me`, () =>
        HttpResponse.json({
          enc_pub: toBase64Url(publicPoint(5n)),
          sig_pub: toBase64Url(publicPoint(6n)),
          blob: '{"v":1}',
          created_at: '2026-10-26T09:00:00+00:00',
          fingerprint,
          fingerprint_display: display,
        })
      )
    );
    const key = await repository().ownKey();
    expect(key?.fingerprintDisplay).toBe(display);
    expect(Array.from(key?.encPub ?? [])).toEqual(Array.from(publicPoint(5n)));
  });

  it('answers null when nothing is enrolled', async () => {
    server.use(
      http.get(`${BASE}/api/admin/recording/keys/me`, () =>
        HttpResponse.json({ detail: { error_code: 'KEY_NOT_ENROLLED', message: 'x' } }, { status: 404 })
      )
    );
    expect(await repository().ownKey()).toBeNull();
  });

  it('surfaces the step-up code on enrolment', async () => {
    server.use(
      http.post(`${BASE}/api/admin/recording/keys`, () =>
        HttpResponse.json({ detail: { error_code: 'STEP_UP_REQUIRED', message: 'x' } }, { status: 403 })
      )
    );
    await expect(
      repository().enrol({ encPub: publicPoint(5n), sigPub: publicPoint(6n) }, '{"v":1}')
    ).rejects.toMatchObject({ serverCode: 'STEP_UP_REQUIRED' });
  });

  it('posts the public keys as base64url and rejects a malformed answer', async () => {
    let posted: unknown = null;
    server.use(
      http.post(`${BASE}/api/admin/recording/keys`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({ fingerprint, fingerprint_display: 'not a fingerprint' }, { status: 201 });
      })
    );
    await expect(
      repository().enrol({ encPub: publicPoint(5n), sigPub: publicPoint(6n) }, '{"v":1}')
    ).rejects.toThrow();
    expect(posted).toEqual({
      enc_pub: toBase64Url(publicPoint(5n)),
      sig_pub: toBase64Url(publicPoint(6n)),
      blob: '{"v":1}',
    });
  });
});
