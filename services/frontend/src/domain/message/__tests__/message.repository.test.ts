import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createMessageRepository } from '@/domain/message/message.repository';

const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });
const client = createHttpClient(config, () => 'en');
const repository = createMessageRepository(client, {
  pipelineTimeoutMs: config.pipelineTimeoutMs,
  apiBaseUrl: config.apiBaseUrl,
});

describe('message repository', () => {
  it('sends text as JSON with the client type', async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post('http://api.test/api/session/A1B2C3D4/message', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          status: 'success',
          message_id: 'm9',
          session_id: 'A1B2C3D4',
          original_text: 'hello',
          translated_text: 'hallo',
          audio_available: true,
          audio_url: '/api/audio/m9.wav',
          processing_time_ms: 900,
          pipeline_type: 'text',
        });
      })
    );

    const result = await repository.sendText('A1B2C3D4', {
      text: 'hello',
      sourceLanguage: 'en',
      targetLanguage: 'de',
      role: 'customer',
    });

    expect(body).toEqual({
      text: 'hello',
      source_lang: 'en',
      target_lang: 'de',
      client_type: 'customer',
    });
    expect(result.messageId).toBe('m9');
    expect(result.audioUrl).toBe('/api/audio/m9.wav');
  });

  it('sends audio as multipart with a file field', async () => {
    let contentType = '';
    server.use(
      http.post('http://api.test/api/session/A1B2C3D4/message', async ({ request }) => {
        contentType = request.headers.get('content-type') ?? '';
        return HttpResponse.json({
          status: 'success',
          message_id: 'm10',
          session_id: 'A1B2C3D4',
          original_text: 'spoken',
          translated_text: 'gesprochen',
          audio_available: true,
          audio_url: '/api/audio/m10.wav',
          processing_time_ms: 4200,
          pipeline_type: 'audio',
        });
      })
    );

    await repository.sendAudio('A1B2C3D4', {
      wav: new Blob(['fake'], { type: 'audio/wav' }),
      sourceLanguage: 'en',
      targetLanguage: 'de',
      role: 'customer',
    });

    expect(contentType).toContain('multipart/form-data');
  });

  it('reads history through the mapper', async () => {
    server.use(
      http.get('http://api.test/api/session/A1B2C3D4/messages', () =>
        HttpResponse.json({
          session_id: 'A1B2C3D4',
          messages: [
            {
              id: 'm1',
              sender: 'admin',
              original_text: 'de text',
              translated_text: 'en text',
              audio_base64: 'AAAA',
              source_lang: 'de',
              target_lang: 'en',
              timestamp: '2026-08-21T10:00:00+00:00',
            },
          ],
        })
      )
    );

    const messages = await repository.getHistory('A1B2C3D4', 'customer');

    expect(messages).toHaveLength(1);
    expect(messages[0].origin).toBe('peer');
    expect(messages[0].text).toBe('en text');
    // The browser fetches this one itself, without axios and its baseURL, so
    // a relative path would be requested from the SPA origin.
    expect(messages[0].audioUrl).toBe('http://api.test/api/audio/m1.wav');
  });

  it('sends text as the admin when told to', async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post('http://api.test/api/session/A1B2C3D4/message', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          status: 'success',
          message_id: 'm1',
          session_id: 'A1B2C3D4',
          original_text: 'Guten Tag',
          translated_text: '\u0645\u0631\u062d\u0628\u0627',
          audio_available: false,
          audio_url: null,
          processing_time_ms: 10,
          pipeline_type: 'text',
        });
      })
    );

    await repository.sendText('A1B2C3D4', {
      text: 'Guten Tag',
      sourceLanguage: 'de',
      targetLanguage: 'ar',
      role: 'admin',
    });

    expect(body.client_type).toBe('admin');
    expect(body.source_lang).toBe('de');
  });

  it('resolves a gateway audio path onto the gateway origin', () => {
    expect(repository.resolveAudioUrl('/api/audio/m9.wav')).toBe(
      'http://api.test/api/audio/m9.wav'
    );
  });
});
