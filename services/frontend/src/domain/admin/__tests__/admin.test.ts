import { describe, expect, it } from 'vitest';
import { toAdminSessions, toCreatedSession } from '@/domain/admin/admin.mapper';
import type { AdminSessionDto } from '@/domain/admin/admin.mapper';
import { isReenterable } from '@/domain/admin/admin.types';

const row = (over: Partial<AdminSessionDto>): AdminSessionDto => ({
  id: 'AAAAAAAA',
  customer_language: 'ar',
  admin_language: 'de',
  status: 'terminated',
  created_at: '2026-08-26T09:00:00+00:00',
  terminated_at: '2026-08-26T09:20:00+00:00',
  message_count: 4,
  admin_connected: false,
  customer_connected: false,
  ...over,
});

describe('toCreatedSession', () => {
  it('keeps the gateway URL verbatim and drops the prose', () => {
    expect(
      toCreatedSession({
        session_id: 'A1B2C3D4',
        client_url: 'https://dialog.kassel.de/join/A1B2C3D4',
        status: 'pending',
        created_at: '2026-08-26T10:00:00+00:00',
        message: 'Session A1B2C3D4 erfolgreich erstellt.',
      })
    ).toEqual({
      id: 'A1B2C3D4',
      clientUrl: 'https://dialog.kassel.de/join/A1B2C3D4',
      createdAt: '2026-08-26T10:00:00+00:00',
    });
  });
});

describe('toAdminSessions', () => {
  it('merges history with the live session', () => {
    const merged = toAdminSessions({
      sessions: [row({ id: 'OLD00001' })],
      active_sessions: [
        row({
          id: 'LIVE0001',
          status: 'active',
          created_at: '2026-08-26T11:00:00+00:00',
          terminated_at: null,
        }),
      ],
    });

    expect(merged.map((entry) => entry.id)).toEqual(['LIVE0001', 'OLD00001']);
  });

  it('orders by start time across both arrays, newest first', () => {
    const merged = toAdminSessions({
      sessions: [
        row({ id: 'MIDDLE01', created_at: '2026-08-26T09:00:00+00:00' }),
        row({ id: 'OLDEST01', created_at: '2026-08-25T09:00:00+00:00' }),
      ],
      active_sessions: [
        row({
          id: 'NEWEST01',
          status: 'pending',
          created_at: '2026-08-26T12:00:00+00:00',
          terminated_at: null,
        }),
      ],
    });

    expect(merged.map((entry) => entry.id)).toEqual(['NEWEST01', 'MIDDLE01', 'OLDEST01']);
  });

  it('breaks a shared start time by id so the order is total', () => {
    const merged = toAdminSessions({
      sessions: [row({ id: 'BBBBBBBB' }), row({ id: 'AAAAAAAA' })],
    });

    expect(merged.map((entry) => entry.id)).toEqual(['AAAAAAAA', 'BBBBBBBB']);
  });

  it('translates the gateway statuses into the three the list shows', () => {
    const merged = toAdminSessions({
      sessions: [
        row({ id: 'TERM0001', status: 'terminated', created_at: '2026-08-26T04:00:00+00:00' }),
        row({ id: 'INACT001', status: 'inactive', created_at: '2026-08-26T03:00:00+00:00' }),
      ],
      active_sessions: [
        row({ id: 'ACTIVE01', status: 'active', created_at: '2026-08-26T06:00:00+00:00' }),
        row({ id: 'PEND0001', status: 'pending', created_at: '2026-08-26T05:00:00+00:00' }),
      ],
    });

    expect(merged.map((entry) => [entry.id, entry.status])).toEqual([
      ['ACTIVE01', 'connected'],
      ['PEND0001', 'open'],
      ['TERM0001', 'completed'],
      ['INACT001', 'completed'],
    ]);
  });

  it('keeps a session whose customer never chose a language', () => {
    const [only] = toAdminSessions({ sessions: [row({ customer_language: null })] });
    expect(only.customerLanguage).toBeNull();
  });

  it('reads an absent terminated_at as null rather than undefined', () => {
    const [only] = toAdminSessions({
      active_sessions: [row({ status: 'pending', terminated_at: undefined })],
    });
    expect(only.terminatedAt).toBeNull();
  });

  it('survives a response with neither array', () => {
    expect(toAdminSessions({})).toEqual([]);
  });
});

describe('isReenterable', () => {
  const session = { id: 'A1B2C3D4', customerLanguage: null, createdAt: '', terminatedAt: null };

  it('admits open and connected sessions', () => {
    expect(isReenterable({ ...session, status: 'open' })).toBe(true);
    expect(isReenterable({ ...session, status: 'connected' })).toBe(true);
  });

  it('refuses a completed session', () => {
    expect(isReenterable({ ...session, status: 'completed' })).toBe(false);
  });
});
