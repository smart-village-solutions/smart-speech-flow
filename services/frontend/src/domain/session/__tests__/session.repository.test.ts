import { describe, expect, it, vi } from 'vitest';
import { createSessionRepository } from '../session.repository';

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
    const repository = createSessionRepository({ post } as never);

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
    const repository = createSessionRepository({ post } as never);

    await repository.activate('ABC12345', 'en', false);

    expect(post).toHaveBeenCalledWith('/api/customer/session/activate', {
      session_id: 'ABC12345',
      customer_language: 'en',
      data_retention_consent: false,
    });
  });
});
