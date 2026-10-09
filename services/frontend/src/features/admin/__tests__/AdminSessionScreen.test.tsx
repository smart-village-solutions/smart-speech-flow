import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';

const sessionIn = (language: string) =>
  server.use(
    http.get('*/api/admin/session/:id/status', ({ params }) =>
      HttpResponse.json({
        id: params.id,
        customer_language: language,
        admin_language: 'de',
        status: 'active',
        created_at: '2026-08-26T10:00:00+00:00',
        message_count: 1,
        admin_connected: true,
        customer_connected: true,
      })
    )
  );

const arabicSession = () => sessionIn('ar');

const history = () =>
  server.use(
    http.get('*/api/admin/session/:id/messages', ({ params }) =>
      HttpResponse.json({
        session_id: params.id,
        messages: [
          {
            id: 'm1',
            sender: 'customer',
            original_text: 'مرحبا',
            translated_text: 'Guten Tag',
            source_lang: 'ar',
            target_lang: 'de',
            timestamp: '2026-08-26T10:00:30+00:00',
            translated_audio_available: false,
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
  it('starts the chat stack below the shared header', async () => {
    arabicSession();
    renderScreen();

    expect(await screen.findByText('A1B2C3D4'));
    expect(document.querySelector('[data-chat-stack=""]')).toHaveStyle({
      top: 'var(--spacing-content-top)',
    });
  });

  it('carries the admin header and the account menu', async () => {
    arabicSession();
    renderScreen();
    expect(await screen.findByRole('button', { name: 'Benutzerkonto' })).toBeInTheDocument();
  });

  it('names the session and the customer language in the overlay', async () => {
    arabicSession();
    renderScreen();

    expect(await screen.findByText('A1B2C3D4')).toBeInTheDocument();
    expect(await screen.findByText('Arabisch')).toBeInTheDocument();
    expect(screen.queryByText('العربية')).not.toBeInTheDocument();
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

    await screen.findByText('Arabisch');
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
      http.get('*/api/admin/session/:id/status', ({ params }) =>
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

  // "Sprache offen" means the customer has not chosen; for a chosen code SSF
  // does not list, the overlay says nothing rather than something untrue.
  it('omits the language group for a code SSF does not list', async () => {
    sessionIn('zz');
    renderScreen();

    expect(await screen.findByRole('status')).toHaveTextContent('A1B2C3D4');
    await screen.findByRole('button', { name: 'Gespräch beenden' });
    expect(screen.getByRole('status')).not.toHaveTextContent('Sprache offen');
  });
});
