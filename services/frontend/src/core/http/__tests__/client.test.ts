import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { AppError } from '@/core/http/AppError';
import { createHttpClient } from '@/core/http/client';
import { readConfig } from '@/app/config/env';

const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });

describe('createHttpClient', () => {
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
