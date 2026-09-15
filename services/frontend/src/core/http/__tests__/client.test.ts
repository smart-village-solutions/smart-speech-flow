import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/setup';
import { AppError } from '@/core/http/AppError';
import { createHttpClient } from '@/core/http/client';
import { readConfig } from '@/app/config/env';
import { getAdminAccessToken } from '@/app/auth/keycloak';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });

describe('createHttpClient', () => {
  beforeEach(() => vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue(null));

  it.each([
    ['tenant-token', 'Bearer tenant-token'],
    [null, null],
  ])('attaches only an available bearer token for token %s', async (token, bearer) => {
    vi.mocked(getAdminAccessToken).mockResolvedValue(token);
    let seen: Headers | undefined;
    server.use(
      http.get('http://api.test/api/admin/history', ({ request }) => {
        seen = request.headers;
        return HttpResponse.json([]);
      })
    );
    await createHttpClient(config, () => 'en').get('/api/admin/history');
    expect(seen?.get('Authorization')).toBe(bearer);
    expect(seen?.get('X-SSF-Legacy-Access')).toBeNull();
  });

  it('keeps the directory anonymous even with an active Keycloak session', async () => {
    vi.mocked(getAdminAccessToken).mockResolvedValue('tenant-token');
    let seen: Headers | undefined;
    server.use(
      http.get('http://api.test/api/login/tenants', ({ request }) => {
        seen = request.headers;
        return HttpResponse.json({ tenants: [] });
      })
    );
    await createHttpClient(config, () => 'en').get('/api/login/tenants');
    expect(seen?.get('Authorization')).toBeNull();
    expect(seen?.get('X-SSF-Legacy-Access')).toBeNull();
    expect(getAdminAccessToken).not.toHaveBeenCalled();
  });

  it('attaches a correlation id and the active locale to every request', async () => {
    let seen: Record<string, string> = {};
    server.use(
      http.get('http://api.test/probe', ({ request }) => {
        seen = {
          correlationId: request.headers.get('X-Correlation-Id') ?? '',
          locale: request.headers.get('Accept-Language') ?? '',
        };
        return HttpResponse.json({ ok: true });
      })
    );

    const client = createHttpClient(config, () => 'ar');
    await client.get('/probe');

    expect(seen.correlationId).toMatch(/^[0-9a-f-]{36}$/);
    expect(seen.locale).toBe('ar');
  });

  // randomUUID exists only in a secure context. An on-site tablet reaching a
  // locally hosted gateway over http:// has none, and this interceptor runs for
  // every request — an unguarded call there fails the whole app, not one call.
  it('still stamps a correlation id where randomUUID is unavailable', async () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });

    try {
      let correlationId = '';
      server.use(
        http.get('http://api.test/insecure', ({ request }) => {
          correlationId = request.headers.get('X-Correlation-Id') ?? '';
          return HttpResponse.json({ ok: true });
        })
      );

      const client = createHttpClient(config, () => 'en');
      await client.get('/insecure');

      expect(correlationId).not.toBe('');
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
    }
  });

  it('rejects with a typed AppError rather than a raw axios error', async () => {
    server.use(http.get('http://api.test/missing', () => new HttpResponse(null, { status: 404 })));

    const client = createHttpClient(config, () => 'en');

    await expect(client.get('/missing')).rejects.toBeInstanceOf(AppError);
    await expect(client.get('/missing')).rejects.toMatchObject({ kind: 'notFound' });
  });

  it('does not force a JSON content type, so FormData keeps its boundary', async () => {
    let contentType = '';
    server.use(
      http.post('http://api.test/upload', ({ request }) => {
        contentType = request.headers.get('Content-Type') ?? '';
        return HttpResponse.json({ ok: true });
      })
    );

    const client = createHttpClient(config, () => 'en');
    const body = new FormData();
    body.append('file', new Blob(['x'], { type: 'audio/wav' }), 'r.wav');
    await client.post('/upload', body);

    expect(contentType).toContain('multipart/form-data');
    expect(contentType).toContain('boundary=');
  });
});
