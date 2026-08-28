import { afterEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { server } from '@/test/setup';
import { AdminNewSessionButton } from '@/features/admin/AdminNewSessionButton';

const START = 'Neues Gespräch starten';

afterEach(() => server.events.removeAllListeners());

const countCreates = () => {
  const calls: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && request.url.includes('/api/admin/session/create')) {
      calls.push(request.url);
    }
  });
  return calls;
};

const renderButton = (liveSessionId: string | null, onEnter = vi.fn()) => {
  renderWithProviders(<AdminNewSessionButton liveSessionId={liveSessionId} onEnter={onEnter} />, {
    locale: 'de',
  });
  return onEnter;
};

describe('AdminNewSessionButton', () => {
  it('creates straight away when nothing is running', async () => {
    installFakeClipboard();
    renderButton(null);

    await userEvent.click(await screen.findByRole('button', { name: START }));

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
    expect(screen.queryByText(/Laufendes Gespräch beenden/)).not.toBeInTheDocument();
  });

  // Decision 5 and 9: the gateway terminates the live session on create, so the
  // UI must say so first rather than discover it afterwards.
  it('warns before ending a running session, naming it', async () => {
    const creates = countCreates();
    renderButton('AR000001');

    await userEvent.click(await screen.findByRole('button', { name: START }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/AR000001/)).toBeInTheDocument();
    expect(creates).toEqual([]);
  });

  it('creates nothing when the warning is dismissed', async () => {
    const creates = countCreates();
    renderButton('AR000001');

    await userEvent.click(await screen.findByRole('button', { name: START }));
    await userEvent.click(await screen.findByRole('button', { name: 'Abbrechen' }));

    expect(creates).toEqual([]);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('creates once the warning is confirmed', async () => {
    installFakeClipboard();
    renderButton('AR000001');

    await userEvent.click(await screen.findByRole('button', { name: START }));
    await userEvent.click(await screen.findByRole('button', { name: 'Trotzdem starten' }));

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
  });

  it('reports a failed creation instead of opening an empty overlay', async () => {
    server.use(
      http.post('*/api/admin/session/create', () => new HttpResponse(null, { status: 500 }))
    );
    renderButton(null);

    await userEvent.click(await screen.findByRole('button', { name: START }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Das Gespräch konnte nicht erstellt werden.'
    );
    expect(screen.queryByText('Neues Gespräch')).not.toBeInTheDocument();
  });

  it('hands the new session id upward when the overlay resolves', async () => {
    installFakeClipboard();
    server.use(
      http.get('*/api/session/:id', ({ params }) =>
        HttpResponse.json({
          id: params.id,
          customer_language: 'ar',
          admin_language: 'de',
          status: 'active',
          created_at: '2026-08-26T12:00:00+00:00',
          message_count: 0,
          admin_connected: true,
          customer_connected: true,
        })
      )
    );
    const onEnter = renderButton(null);

    await userEvent.click(await screen.findByRole('button', { name: START }));

    await waitFor(() => expect(onEnter).toHaveBeenCalledWith('A1B2C3D4'));
  });
  // A code read aloud and then cancelled must stop working: otherwise the
  // customer joins a conversation nobody is watching.
  it('terminates the session it created when the invite is cancelled', async () => {
    installFakeClipboard();
    const deletes: string[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'DELETE') {
        deletes.push(request.url);
      }
    });
    renderButton(null);

    await userEvent.click(await screen.findByRole('button', { name: START }));
    await userEvent.click(await screen.findByRole('button', { name: 'Abbrechen' }));

    await vi.waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0]).toContain('/api/admin/session/A1B2C3D4/terminate');
    expect(screen.queryByText('Neues Gespräch')).not.toBeInTheDocument();
  });
});
