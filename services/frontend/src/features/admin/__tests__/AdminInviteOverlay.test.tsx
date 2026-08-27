import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { server } from '@/test/setup';
import { AdminInviteOverlay } from '@/features/admin/AdminInviteOverlay';
import type { CreatedSession } from '@/domain/admin/admin.types';

const SESSION: CreatedSession = {
  id: 'A1B2C3D4',
  clientUrl: 'https://translate.smart-village.solutions/join/A1B2C3D4',
  createdAt: '2026-08-26T12:00:00+00:00',
};

const joined = (customerConnected: boolean) =>
  server.use(
    http.get('*/api/session/:id', ({ params }) =>
      HttpResponse.json({
        id: params.id,
        customer_language: customerConnected ? 'ar' : null,
        admin_language: 'de',
        status: customerConnected ? 'active' : 'pending',
        created_at: '2026-08-26T12:00:00+00:00',
        message_count: 0,
        admin_connected: true,
        customer_connected: customerConnected,
      })
    )
  );

const renderOverlay = (
  session: CreatedSession | null,
  handlers: { onEnter?: () => void; onCancel?: () => void } = {},
  brand: 'ssf' | 'kassel' = 'ssf'
) =>
  renderWithProviders(
    <AdminInviteOverlay
      session={session}
      onEnter={handlers.onEnter ?? vi.fn()}
      onCancel={handlers.onCancel ?? vi.fn()}
    />,
    { locale: 'de', brand }
  );

describe('AdminInviteOverlay', () => {
  it('renders nothing before a session exists', () => {
    renderOverlay(null);
    expect(screen.queryByText('Neues Gespräch')).not.toBeInTheDocument();
  });

  it('shows the code the gateway issued as eight boxes', async () => {
    joined(false);
    renderOverlay(SESSION);

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
    // Radix portals the content, so the query goes to the document.
    await waitFor(() => expect(document.querySelectorAll('[data-code-box]')).toHaveLength(8));
  });

  it('shows the gateway URL verbatim', async () => {
    joined(false);
    renderOverlay(SESSION);

    expect(await screen.findByText(SESSION.clientUrl)).toBeInTheDocument();
  });

  // Decision 10: the URL comes from CLIENT_BASE_URL on the server. A frontend
  // brand-to-domain map is exactly what this asserts is absent.
  it('does not rebuild the URL per brand', async () => {
    joined(false);
    const { unmount } = renderOverlay(SESSION, {}, 'ssf');
    expect(await screen.findByText(SESSION.clientUrl)).toBeInTheDocument();
    unmount();

    renderOverlay(SESSION, {}, 'kassel');
    expect(await screen.findByText(SESSION.clientUrl)).toBeInTheDocument();
  });

  it('copies that same URL and nothing else', async () => {
    joined(false);
    const clipboard = installFakeClipboard();
    renderOverlay(SESSION);

    await userEvent.click(await screen.findByRole('button', { name: /Link kopieren/ }));

    expect(clipboard.written).toEqual([SESSION.clientUrl]);
    expect(await screen.findByText('Kopiert ✓')).toBeInTheDocument();
  });

  it('keeps the link readable when the clipboard refuses', async () => {
    joined(false);
    installFakeClipboard({ fail: true });
    renderOverlay(SESSION);

    await userEvent.click(await screen.findByRole('button', { name: /Link kopieren/ }));

    expect(await screen.findByText('Kopieren nicht möglich')).toBeInTheDocument();
    expect(screen.getByText(SESSION.clientUrl)).toBeInTheDocument();
  });

  it('waits while the customer has not joined', async () => {
    joined(false);
    const onEnter = vi.fn();
    renderOverlay(SESSION, { onEnter });

    expect(await screen.findByText(/startet automatisch/)).toBeInTheDocument();
    expect(onEnter).not.toHaveBeenCalled();
  });

  it('resolves on its own once the customer has joined', async () => {
    joined(true);
    const onEnter = vi.fn();
    renderOverlay(SESSION, { onEnter });

    await waitFor(() => expect(onEnter).toHaveBeenCalledWith('A1B2C3D4'));
  });

  it('resolves on demand, without waiting for the poll', async () => {
    joined(false);
    const onEnter = vi.fn();
    renderOverlay(SESSION, { onEnter });

    await userEvent.click(await screen.findByRole('button', { name: 'Zum Gespräch wechseln' }));

    expect(onEnter).toHaveBeenCalledWith('A1B2C3D4');
  });

  it('cancels without entering anything', async () => {
    joined(false);
    const onCancel = vi.fn();
    const onEnter = vi.fn();
    renderOverlay(SESSION, { onEnter, onCancel });

    await userEvent.click(await screen.findByRole('button', { name: 'Abbrechen' }));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onEnter).not.toHaveBeenCalled();
  });
});
