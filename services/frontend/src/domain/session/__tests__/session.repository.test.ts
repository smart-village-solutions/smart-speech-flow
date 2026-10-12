import { describe, expect, it, vi } from 'vitest';
import { createSessionRepository } from '../session.repository';

function tokens(held: string | null = null) {
  return { read: vi.fn<(sessionId: string) => string | null>(() => held), save: vi.fn() };
}

const activateResponseFixture = {
  session_id: 'ABC12345',
  status: 'active' as const,
  customer_language: 'en',
  message: 'ok',
  timestamp: '2026-09-17T10:00:00+00:00',
};

describe('SessionRepository.activate', () => {
  it('sends the consent answer on the activation request', async () => {
    const post = vi.fn().mockResolvedValue({ data: activateResponseFixture });
    const repository = createSessionRepository({ post } as never, tokens());

    await repository.activate('ABC12345', 'en', true);

    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith(
      '/api/customer/session/activate',
      { session_id: 'ABC12345', customer_language: 'en', data_retention_consent: true },
      expect.anything()
    );
  });

  it('sends false when the guest did not agree', async () => {
    const post = vi.fn().mockResolvedValue({ data: activateResponseFixture });
    const repository = createSessionRepository({ post } as never, tokens());

    await repository.activate('ABC12345', 'en', false);

    expect(post).toHaveBeenCalledWith(
      '/api/customer/session/activate',
      { session_id: 'ABC12345', customer_language: 'en', data_retention_consent: false },
      expect.anything()
    );
  });
});

describe('SessionRepository guest token', () => {
  it('chooses and keeps the token before it asks, so a lost answer can be retried', async () => {
    const store = tokens();
    const post = vi.fn().mockImplementation((_url, _body, config) => {
      // Kept before the request leaves, so a retry after a lost answer has it.
      expect(store.save).toHaveBeenCalledWith('ABC12345', config.headers['X-Guest-Token']);
      return Promise.resolve({
        data: { ...activateResponseFixture, guest_token: config.headers['X-Guest-Token'] },
      });
    });

    await createSessionRepository({ post } as never, store).activate('ABC12345', 'en', true);

    const sent = post.mock.calls[0][2].headers['X-Guest-Token'] as string;
    expect(sent).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it('sends the token it already holds for the session', async () => {
    const post = vi.fn().mockResolvedValue({ data: { ...activateResponseFixture, guest_token: null } });

    await createSessionRepository({ post } as never, tokens('held-token')).activate('ABC12345', 'tr', true);

    expect(post.mock.calls[0][2]).toEqual({ headers: { 'X-Guest-Token': 'held-token' } });
  });

  it('adopts a token the server chose instead', async () => {
    const store = tokens();
    const post = vi.fn().mockResolvedValue({
      data: { ...activateResponseFixture, guest_token: 'server-chosen' },
    });

    await createSessionRepository({ post } as never, store).activate('ABC12345', 'en', true);

    expect(store.save).toHaveBeenLastCalledWith('ABC12345', 'server-chosen');
  });

  it('asks the session route for a guest socket ticket', async () => {
    const post = vi.fn().mockResolvedValue({ data: { ticket: 'one-time', expires_at: 'later' } });

    const ticket = await createSessionRepository({ post } as never, tokens()).issueGuestTicket(
      'ABC12345'
    );

    expect(ticket).toBe('one-time');
    expect(post).toHaveBeenCalledWith('/api/customer/session/ABC12345/realtime-ticket');
  });
});
