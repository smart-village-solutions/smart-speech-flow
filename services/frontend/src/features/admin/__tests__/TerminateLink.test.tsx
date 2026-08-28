import { afterEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { TerminateLink } from '@/features/admin/TerminateLink';

const LINK = 'Gespräch beenden';

afterEach(() => server.events.removeAllListeners());

const countDeletes = () => {
  const calls: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'DELETE') {
      calls.push(request.url);
    }
  });
  return calls;
};

describe('TerminateLink', () => {
  it('asks before ending anything', async () => {
    const deletes = countDeletes();
    renderWithProviders(<TerminateLink sessionId="A1B2C3D4" onTerminated={vi.fn()} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: LINK }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/A1B2C3D4/)).toBeInTheDocument();
    expect(deletes).toEqual([]);
  });

  it('ends nothing when the question is dismissed', async () => {
    const deletes = countDeletes();
    const onTerminated = vi.fn();
    renderWithProviders(<TerminateLink sessionId="A1B2C3D4" onTerminated={onTerminated} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: LINK }));
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));

    expect(deletes).toEqual([]);
    expect(onTerminated).not.toHaveBeenCalled();
  });

  it('terminates the session and hands control back', async () => {
    const deletes = countDeletes();
    const onTerminated = vi.fn();
    renderWithProviders(<TerminateLink sessionId="A1B2C3D4" onTerminated={onTerminated} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: LINK }));
    await userEvent.click(screen.getByRole('button', { name: 'Beenden' }));

    await vi.waitFor(() => expect(onTerminated).toHaveBeenCalledOnce());
    expect(deletes.at(0)).toContain('/api/admin/session/A1B2C3D4/terminate');
  });

  // A failed terminate must not look like a successful one: the conversation is
  // still live, so the screen stays where it is and says so.
  it('keeps the question open and says so when the gateway refuses', async () => {
    server.use(
      http.delete(
        '*/api/admin/session/:id/terminate',
        () => new HttpResponse(null, { status: 500 })
      )
    );
    const onTerminated = vi.fn();
    renderWithProviders(<TerminateLink sessionId="A1B2C3D4" onTerminated={onTerminated} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: LINK }));
    await userEvent.click(screen.getByRole('button', { name: 'Beenden' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Das Gespräch konnte nicht beendet werden.'
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(onTerminated).not.toHaveBeenCalled();
  });
});
