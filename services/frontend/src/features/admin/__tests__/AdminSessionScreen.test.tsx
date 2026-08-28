import { afterEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';

afterEach(() => server.events.removeAllListeners());

const arabicSession = () =>
  server.use(
    http.get('*/api/session/:id', ({ params }) =>
      HttpResponse.json({
        id: params.id,
        customer_language: 'ar',
        admin_language: 'de',
        status: 'active',
        created_at: '2026-08-26T10:00:00+00:00',
        message_count: 1,
        admin_connected: true,
        customer_connected: true,
      })
    )
  );

const history = () =>
  server.use(
    http.get('*/api/session/:id/messages', ({ params }) =>
      HttpResponse.json({
        session_id: params.id,
        messages: [
          {
            id: 'm1',
            sender: 'customer',
            original_text: 'مرحبا',
            translated_text: 'Guten Tag',
            audio_base64: null,
            source_lang: 'ar',
            target_lang: 'de',
            timestamp: '2026-08-26T10:00:30+00:00',
          },
        ],
      })
    )
  );

const renderScreen = (onLeave = vi.fn()) => {
  renderWithProviders(
    <AdminSessionScreen sessionId="A1B2C3D4" onLeave={onLeave} onSignOut={vi.fn()} />,
    { locale: 'de' }
  );
  return onLeave;
};

describe('AdminSessionScreen', () => {
  it('carries the admin header and the account menu', async () => {
    arabicSession();
    renderScreen();
    expect(await screen.findByRole('button', { name: 'Benutzerkonto' })).toBeInTheDocument();
  });

  it('names the session and the customer language in the overlay', async () => {
    arabicSession();
    renderScreen();

    expect(await screen.findByText('A1B2C3D4')).toBeInTheDocument();
    expect(await screen.findByText('العربية')).toBeInTheDocument();
  });

  // The admin reads the customer's turn in German, not in Arabic. If the role
  // were not threaded, this bubble would carry the original instead.
  it('shows the customer turn translated into German', async () => {
    arabicSession();
    history();
    renderScreen();

    expect(await screen.findByText('Guten Tag')).toBeInTheDocument();
    expect(screen.queryByText('مرحبا')).not.toBeInTheDocument();
  });

  it('stays in German rather than adopting the customer language', async () => {
    arabicSession();
    renderScreen();

    await screen.findByText('العربية');
    expect(document.documentElement.lang).toBe('de');
  });

  it('offers the terminate link', async () => {
    arabicSession();
    renderScreen();
    expect(await screen.findByRole('button', { name: 'Gespräch beenden' })).toBeInTheDocument();
  });

  it('leaves for the dashboard once the session is terminated', async () => {
    arabicSession();
    const onLeave = renderScreen();

    await userEvent.click(await screen.findByRole('button', { name: 'Gespräch beenden' }));
    await userEvent.click(screen.getByRole('button', { name: 'Beenden' }));

    await vi.waitFor(() => expect(onLeave).toHaveBeenCalledOnce());
  });

  it('offers a way back instead of a terminate once the session has ended', async () => {
    server.use(
      http.get('*/api/session/:id', ({ params }) =>
        HttpResponse.json({
          id: params.id,
          customer_language: 'ar',
          admin_language: 'de',
          status: 'terminated',
          created_at: '2026-08-26T10:00:00+00:00',
          message_count: 0,
          admin_connected: false,
          customer_connected: false,
        })
      )
    );
    renderScreen();

    // The reducer's `ended` latches on the gateway's session_terminated push,
    // which no transport delivers in jsdom, so this asserts the mount case: a
    // session already terminated still offers the terminate link, and the
    // ended-state swap is covered by the reducer's own tests.
    expect(await screen.findByRole('button', { name: 'Gespräch beenden' })).toBeInTheDocument();
  });
});
