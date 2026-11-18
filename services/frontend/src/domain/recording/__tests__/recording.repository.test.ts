import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { toBase64Url } from '@/core/crypto/bytes';
import { publicPoint } from '@/core/crypto/curve';
import { createHttpClient } from '@/core/http/client';
import { createKeyConfirmationRepository } from '@/domain/recording/keyConfirmation.repository';
import { createRecordingKeysRepository } from '@/domain/recording/recording.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const fingerprint = toBase64Url(new Uint8Array(32).fill(7));
const display = '0707 0707 0707 0707 0707 0707 0707 0707 0707 0707';

function repository() {
  return createRecordingKeysRepository(
    createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de')
  );
}

describe('recording keys repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads the authenticated effective passphrase-file policy', async () => {
    server.use(
      http.get(`${BASE}/api/admin/recording/key-policy`, ({ request }) => {
        expect(request.headers.get('Authorization')).toBe('Bearer staff-token');
        return HttpResponse.json({ passphrase_file_enabled: true });
      })
    );
    await expect(repository().passphraseFileEnabled()).resolves.toBe(true);
  });

  it('rejects malformed passphrase-file policy values', async () => {
    server.use(
      http.get(`${BASE}/api/admin/recording/key-policy`, () =>
        HttpResponse.json({ passphrase_file_enabled: 'true' })
      )
    );
    await expect(repository().passphraseFileEnabled()).rejects.toThrow();
  });

  it('reads the active and superseded versions from the authenticated V2 resource', async () => {
    const meta = {
      encPub: toBase64Url(publicPoint(5n)),
      sigPub: toBase64Url(publicPoint(6n)),
      fingerprint,
      createdAt: '2026-10-26T09:00:00Z',
    };
    server.use(
      http.get(`${BASE}/api/admin/recording/v2/keys/me`, () =>
        HttpResponse.json({
          activeVersion: 3,
          versions: [
            { ...meta, version: 2, state: 'superseded' },
            { ...meta, version: 3, state: 'active' },
          ],
        })
      ),
      http.get(`${BASE}/api/admin/recording/v2/keys/me/:version`, ({ params, request }) => {
        expect(request.headers.get('Authorization')).toBe('Bearer staff-token');
        const version = Number(params.version);
        return HttpResponse.json({
          ...meta,
          version,
          state: version === 3 ? 'active' : 'superseded',
          blob: 'sealed',
        });
      })
    );
    expect((await repository().ownKey())?.fingerprintDisplay).toBe(display);
    expect((await repository().version(2)).keyVersion).toBe(2);
  });
  it('rejects an unusable or mismatched version', async () => {
    server.use(
      http.get(`${BASE}/api/admin/recording/v2/keys/me/2`, () =>
        HttpResponse.json({
          version: 2,
          state: 'revoked',
          encPub: toBase64Url(publicPoint(5n)),
          sigPub: toBase64Url(publicPoint(6n)),
          fingerprint,
          createdAt: 'today',
          blob: 'sealed',
        })
      )
    );
    await expect(repository().version(2)).rejects.toThrow();
  });
  it('answers null when nothing is enrolled', async () => {
    expect(await repository().ownKey()).toBeNull();
  });

  it('surfaces the step-up code on enrolment', async () => {
    server.use(
      http.post(`${BASE}/api/admin/recording/keys`, () =>
        HttpResponse.json(
          { detail: { error_code: 'STEP_UP_REQUIRED', message: 'x' } },
          { status: 403 }
        )
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
        return HttpResponse.json(
          { fingerprint, fingerprint_display: 'not a fingerprint' },
          { status: 201 }
        );
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

  it('re-enrols under the version it replaces and reads the status', async () => {
    let sent: unknown;
    server.use(
      http.post(`${BASE}/api/admin/recording/keys/reenrolment`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          { status: 'pending_confirmation', fingerprint, fingerprint_display: display },
          { status: 201 }
        );
      }),
      http.get(`${BASE}/api/admin/recording/keys/reenrolment`, () =>
        HttpResponse.json({
          custodian: true,
          k: 2,
          usable_after: 1,
          pending: {
            fingerprint,
            fingerprint_display: display,
            expires_at: '2026-11-02T10:00:00+00:00',
          },
        })
      )
    );
    const repo = repository();
    const done = await repo.reenrol(
      { encPub: publicPoint(5n), sigPub: publicPoint(6n) },
      '{"v":1}',
      2
    );
    expect(done.status).toBe('pending_confirmation');
    expect(sent).toMatchObject({ blob: '{"v":1}', replaces_version: 2 });
    expect(await repo.reenrolmentImpact()).toEqual({
      custodian: true,
      k: 2,
      usableAfter: 1,
      pending: { fingerprintDisplay: display, expiresAt: '2026-11-02T10:00:00+00:00' },
    });
  });

  it('refuses a status it does not know', async () => {
    server.use(
      http.post(`${BASE}/api/admin/recording/keys/reenrolment`, () =>
        HttpResponse.json({ status: 'maybe', fingerprint, fingerprint_display: display })
      )
    );
    await expect(
      repository().reenrol({ encPub: publicPoint(5n), sigPub: publicPoint(6n) }, '{"v":1}', 1)
    ).rejects.toThrow();
  });
});

describe('key confirmation repository', () => {
  const token = 'A'.repeat(43);
  const confirmation = () =>
    createKeyConfirmationRepository(
      createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de')
    );

  it('looks the link up without a login and posts only the token', async () => {
    let sent: unknown;
    let authorization: string | null = 'unset';
    server.use(
      http.post(`${BASE}/api/recording/key-confirmation/lookup`, async ({ request }) => {
        sent = await request.json();
        authorization = request.headers.get('Authorization');
        return HttpResponse.json({
          fingerprint,
          fingerprint_display: display,
          requested_at: '2026-11-02T09:30:00+00:00',
          expires_at: '2026-11-02T10:00:00+00:00',
        });
      })
    );
    expect(await confirmation().lookup(token)).toEqual({
      fingerprintDisplay: display,
      requestedAt: '2026-11-02T09:30:00+00:00',
      expiresAt: '2026-11-02T10:00:00+00:00',
    });
    expect(sent).toEqual({ token });
    expect(authorization).toBeNull();
    expect(getAdminAccessToken).not.toHaveBeenCalled();
  });

  it('confirms and declines', async () => {
    const declined = vi.fn();
    server.use(
      http.post(`${BASE}/api/recording/key-confirmation/confirm`, () =>
        HttpResponse.json({ fingerprint, fingerprint_display: display })
      ),
      http.post(`${BASE}/api/recording/key-confirmation/decline`, () => {
        declined();
        return new HttpResponse(null, { status: 204 });
      })
    );
    expect((await confirmation().confirm(token)).fingerprintDisplay).toBe(display);
    await confirmation().decline(token);
    expect(declined).toHaveBeenCalledOnce();
  });

  it('surfaces the refusal code', async () => {
    server.use(
      http.post(`${BASE}/api/recording/key-confirmation/confirm`, () =>
        HttpResponse.json({ detail: { error_code: 'LINK_EXPIRED', message: 'x' } }, { status: 410 })
      )
    );
    await expect(confirmation().confirm(token)).rejects.toMatchObject({
      serverCode: 'LINK_EXPIRED',
    });
  });
});
