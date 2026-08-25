import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createSessionRepository } from '@/domain/session/session.repository';
import { mergeActivatedSession } from '@/domain/session/session.mapper';
import { isJoinable, type Session } from '@/domain/session/session.types';

const client = createHttpClient(readConfig({ VITE_API_BASE_URL: 'http://api.test' }), () => 'en');
const repository = createSessionRepository(client);

describe('session repository', () => {
  it('maps the gateway id field onto the domain id', async () => {
    server.use(
      http.get('http://api.test/api/session/A1B2C3D4', () =>
        HttpResponse.json({
          id: 'A1B2C3D4',
          customer_language: null,
          admin_language: 'de',
          status: 'pending',
          created_at: '2026-08-21T10:00:00+00:00',
          message_count: 3,
          admin_connected: true,
          customer_connected: false,
        })
      )
    );

    const session = await repository.getSession('A1B2C3D4');

    expect(session).toEqual({
      id: 'A1B2C3D4',
      status: 'pending',
      customerLanguage: null,
      adminLanguage: 'de',
      createdAt: '2026-08-21T10:00:00+00:00',
      messageCount: 3,
      adminConnected: true,
      customerConnected: false,
    });
  });

  it('rejects a malformed session id before it reaches the network', async () => {
    await expect(repository.getSession('nope')).rejects.toThrow('Invalid session identifier');
  });

  it('activates a session and returns the updated domain model', async () => {
    server.use(
      http.post('http://api.test/api/customer/session/activate', async ({ request }) => {
        const body = (await request.json()) as Record<string, string>;
        expect(body).toEqual({ session_id: 'A1B2C3D4', customer_language: 'ar' });
        return HttpResponse.json({
          session_id: 'A1B2C3D4',
          status: 'active',
          customer_language: 'ar',
          message: 'ok',
          timestamp: '2026-08-21T10:00:00+00:00',
        });
      })
    );

    const session = await repository.activate('A1B2C3D4', 'ar');

    expect(session.status).toBe('active');
    expect(session.customerLanguage).toBe('ar');
  });
});

describe('isJoinable', () => {
  const base = {
    id: 'A1B2C3D4',
    customerLanguage: null,
    adminLanguage: 'de',
    createdAt: '2026-08-21T10:00:00+00:00',
    messageCount: 0,
    adminConnected: false,
    customerConnected: false,
  };

  it('accepts pending and active sessions', () => {
    expect(isJoinable({ ...base, status: 'pending' })).toBe(true);
    expect(isJoinable({ ...base, status: 'active' })).toBe(true);
  });

  it('rejects terminated and inactive sessions', () => {
    expect(isJoinable({ ...base, status: 'terminated' })).toBe(false);
    expect(isJoinable({ ...base, status: 'inactive' })).toBe(false);
  });
});

describe('mergeActivatedSession', () => {
  const previous: Session = {
    id: 'A1B2C3D4',
    status: 'pending',
    customerLanguage: null,
    adminLanguage: 'tr',
    createdAt: '2026-08-21T10:00:00+00:00',
    messageCount: 4,
    adminConnected: true,
    customerConnected: false,
  };

  // The activation response has no admin_language field, so the mapper fills
  // one in. Where the session has already been read, that read is the truth.
  it('keeps what activation cannot know', () => {
    const activated: Session = {
      ...previous,
      status: 'active',
      customerLanguage: 'en',
      adminLanguage: 'de',
      messageCount: 0,
      adminConnected: false,
      customerConnected: true,
    };

    expect(mergeActivatedSession(activated, previous)).toEqual({
      ...previous,
      status: 'active',
      customerLanguage: 'en',
      customerConnected: true,
    });
  });

  it('takes the activation whole when nothing was read before', () => {
    const activated: Session = { ...previous, status: 'active', customerLanguage: 'en' };

    expect(mergeActivatedSession(activated, undefined)).toBe(activated);
  });
});
