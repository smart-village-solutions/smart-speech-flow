import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readConfig } from '@/app/config/env';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { createHttpClient } from '@/core/http/client';
import { createContentRepository } from '@/domain/content/content.repository';
import { server } from '@/test/setup';
import {
  guestContentBody,
  guestLanguagesBody,
  installationBody,
  staffContentBody,
} from '@/test/contentFixtures';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const SESSION = 'A1B2C3D4';

function repository() {
  return createContentRepository(
    createHttpClient(readConfig({ VITE_API_BASE_URL: 'http://api.test' }), () => 'de')
  );
}

/** Answers `body` on `path` and records the Authorization header of each request. */
function serve(path: string, body: unknown): (string | null)[] {
  const authorizations: (string | null)[] = [];
  server.use(
    http.get(`http://api.test${path}`, ({ request }) => {
      authorizations.push(request.headers.get('Authorization'));
      return HttpResponse.json(body);
    })
  );
  return authorizations;
}

type Repo = ReturnType<typeof repository>;

/** Answers `body` on `path` and records one request header of each request. */
function serveRecording(path: string, body: unknown, header: string): (string | null)[] {
  const values: (string | null)[] = [];
  server.use(
    http.get(`http://api.test${path}`, ({ request }) => {
      values.push(request.headers.get(header));
      return HttpResponse.json(body);
    })
  );
  return values;
}

describe('content repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads installation content anonymously', async () => {
    const authorizations = serve('/api/content/installation', installationBody);

    await expect(repository().getPublic()).resolves.toMatchObject({ locale: 'de-DE' });
    expect(authorizations).toEqual([null]);
  });

  it('reads guest languages by session key, without a token', async () => {
    const authorizations = serve(`/api/customer/session/${SESSION}/languages`, guestLanguagesBody);

    await expect(repository().getGuestLanguages(SESSION)).resolves.toHaveLength(9);
    expect(authorizations).toEqual([null]);
  });

  it('reads guest content by session key and language, without a token', async () => {
    const authorizations = serve(
      `/api/customer/session/${SESSION}/content/en`,
      guestContentBody('en')
    );

    await expect(repository().getGuest(SESSION, 'en')).resolves.toMatchObject({ provided: true });
    expect(authorizations).toEqual([null]);
  });

  it('sends the staff bearer token to /api/admin/content', async () => {
    const authorizations = serve('/api/admin/content', staffContentBody);

    await expect(repository().getStaff()).resolves.toMatchObject({ timeZone: 'Europe/Berlin' });
    expect(authorizations).toEqual(['Bearer staff-token']);
  });

  it.each([
    ['a malformed session id', () => repository().getGuestLanguages('../admin')],
    ['a malformed session id for content', () => repository().getGuest('../admin', 'en')],
    ['a malformed language', () => repository().getGuest(SESSION, '../../admin')],
  ])('refuses %s before any request', async (_label, call) => {
    await expect(call()).rejects.toThrow(/Invalid (session|language) identifier/);
  });

  it.each([
    [
      'installation',
      '/api/content/installation',
      installationBody,
      (r: Repo) => r.getPublic({ fresh: true }),
    ],
    [
      'guest',
      `/api/customer/session/${SESSION}/content/en`,
      guestContentBody('en'),
      (r: Repo) => r.getGuest(SESSION, 'en', { fresh: true }),
    ],
    ['staff', '/api/admin/content', staffContentBody, (r: Repo) => r.getStaff({ fresh: true })],
  ])(
    'reads %s content past the browser cache when asked for a fresh copy',
    async (_name, path, body, read) => {
      // The installation route allows 60 s of browser caching; a reload after a
      // changed form must not be answered from that copy.
      const cacheControl = serveRecording(path, body, 'Cache-Control');

      await read(repository());

      expect(cacheControl).toEqual(['no-cache']);
    }
  );

  it('leaves the browser cache alone for an ordinary read', async () => {
    const cacheControl = serveRecording(
      '/api/content/installation',
      installationBody,
      'Cache-Control'
    );

    await repository().getPublic();

    expect(cacheControl).toEqual([null]);
  });

  it('rejects a 503, so the caller falls back', async () => {
    server.use(
      http.get('http://api.test/api/admin/content', () =>
        HttpResponse.json({ detail: 'Studio content is temporarily unavailable' }, { status: 503 })
      )
    );

    await expect(repository().getStaff()).rejects.toMatchObject({ kind: 'server' });
  });

  it('rejects a body the mapper refuses', async () => {
    serve('/api/content/installation', { revision: 'sha256:x' });

    await expect(repository().getPublic()).rejects.toThrow();
  });
});
