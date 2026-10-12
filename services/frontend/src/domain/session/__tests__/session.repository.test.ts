import { describe, expect, it, vi } from 'vitest';
import { createSessionRepository } from '../session.repository';

const tokens = () => ({ read: vi.fn(() => null), save: vi.fn() });

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
    expect(post).toHaveBeenCalledWith('/api/customer/session/activate', {
      session_id: 'ABC12345',
      customer_language: 'en',
      data_retention_consent: true,
    });
  });

  it('sends false when the guest did not agree', async () => {
    const post = vi.fn().mockResolvedValue({ data: activateResponseFixture });
    const repository = createSessionRepository({ post } as never, tokens());

    await repository.activate('ABC12345', 'en', false);

    expect(post).toHaveBeenCalledWith('/api/customer/session/activate', {
      session_id: 'ABC12345',
      customer_language: 'en',
      data_retention_consent: false,
    });
  });
});

describe('SessionRepository guest token', () => {
  it('keeps the token the claiming activation returns', async () => {
    const store = tokens();
    const post = vi.fn().mockResolvedValue({
      data: { ...activateResponseFixture, guest_token: 'claimed' },
    });

    await createSessionRepository({ post } as never, store).activate('ABC12345', 'en', true);

    expect(store.save).toHaveBeenCalledWith('ABC12345', 'claimed');
  });

  it('keeps nothing from a repeated activation', async () => {
    const store = tokens();
    const post = vi.fn().mockResolvedValue({
      data: { ...activateResponseFixture, guest_token: null },
    });

    await createSessionRepository({ post } as never, store).activate('ABC12345', 'tr', true);

    expect(store.save).not.toHaveBeenCalled();
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
