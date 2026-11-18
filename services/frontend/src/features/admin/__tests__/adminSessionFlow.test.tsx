import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { conversationRow } from '@/test/dashboardFixtures';
import { createRealtimeWire } from '@/test/realtimeWire';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { readConfig } from '@/app/config/env';
import { AppRoutes } from '@/app/router/AppRoutes';

vi.mock('@/app/auth/keycloak', () => ({
  getAdminIdentity: () => ({ tenantId: 'tenant-kassel', userSub: 'alice' }),
  requireKeycloakLogin: vi.fn().mockResolvedValue(true),
  getAdminAccessToken: vi.fn().mockResolvedValue('tenant-token'),
  getStudioAdministrationUrl: vi.fn().mockReturnValue(null),
  hasPermission: () => false,
  getAccountConsoleUrl: vi.fn().mockReturnValue(null),
  logoutFromKeycloak: vi.fn().mockResolvedValue(undefined),
  subscribeToKeycloakAuthorization: () => () => {},
  subscribeToKeycloakExpiration: () => () => {},
}));

const services = { config: readConfig({}) };

const renderApp = () =>
  renderWithProviders(<AppRoutes />, {
    route: '/login/tenant-kassel',
    locale: 'de',
    services,
  });

describe('the admin session flow', () => {
  beforeEach(() => sessionStorage.clear());

  it('creates a session, hands out the invite, and enters the conversation', async () => {
    installFakeClipboard();
    renderApp();

    await userEvent.click(await screen.findByRole('button', { name: 'Neues Gespräch starten' }));

    // The MSW history fixture holds a live session, so the warning comes first.
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Trotzdem starten' }));

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
    expect(screen.getByText('http://localhost:5173/join/A1B2C3D4')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Zum Gespräch wechseln' }));

    // The conversation screen names the session in its status overlay.
    expect(await screen.findByRole('status')).toHaveTextContent('A1B2C3D4');
  });

  it('removes the new session’s Resume action when its invitation is cancelled', async () => {
    const id = 'AR000002';
    let state: 'absent' | 'active' | 'ended' = 'absent';
    server.use(
      http.get('*/api/admin/dashboard/conversations', () =>
        HttpResponse.json({
          items: state === 'absent' ? [] : [conversationRow(id, state === 'active')],
          next_cursor: null,
        })
      ),
      http.get('*/api/admin/session/current', () => HttpResponse.json({}, { status: 404 })),
      http.post('*/api/admin/session/create', () => {
        state = 'active';
        return HttpResponse.json(
          {
            session_id: id,
            client_url: 'https://example.test/join/' + id,
            status: 'pending',
            created_at: '2026-11-18T12:00:00Z',
          },
          { status: 201 }
        );
      }),
      http.delete('*/api/admin/session/:id/terminate', () => {
        state = 'ended';
        return HttpResponse.json({ session_id: id, status: 'terminated' });
      })
    );
    renderApp();
    await userEvent.click(await screen.findByRole('button', { name: 'Neues Gespräch starten' }));
    await screen.findByRole('dialog');
    // Radix hides the underlying list from assistive technology until the invitation closes.
    const resume = 'button[aria-label="Gespräch AR000002 fortsetzen"]';
    await waitFor(() => expect(document.querySelector(resume)).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(state).toBe('ended'));
    await waitFor(() => expect(document.querySelector(resume)).not.toBeInTheDocument());
  });

  it('keeps one connected live session and its unsent draft while the account is open', async () => {
    const wire = createRealtimeWire();
    const createRealtime = vi.fn(() => wire.transport);
    renderWithProviders(<AppRoutes />, {
      route: '/login/tenant-kassel',
      locale: 'de',
      services: { ...services, createRealtime },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Tastatur öffnen' }));
    await userEvent.type(screen.getByRole('textbox'), 'Entwurf');
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mein Konto' }));
    expect(await screen.findByRole('heading', { name: 'Mein Konto' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Gespräch beenden' })).not.toBeInTheDocument();
    expect(wire.transport.disconnect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    if (!screen.queryByRole('textbox'))
      await userEvent.click(await screen.findByRole('button', { name: 'Tastatur öffnen' }));
    expect(screen.getByRole('textbox')).toHaveValue('Entwurf');
    expect(createRealtime).toHaveBeenCalledTimes(1);
    expect(wire.transport.connect).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    await screen.findByRole('link', { name: 'Stadt Kassel' });
    expect(wire.transport.disconnect).toHaveBeenCalledTimes(1);
  });

  it('re-enters a session that is still open', async () => {
    renderApp();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );

    expect(await screen.findByRole('status')).toHaveTextContent('AR000001');
  });

  it('leaves a completed session alone', async () => {
    renderApp();

    // Waiting on the rows, not the heading: the heading renders before the
    // query answers, and "no button for TR000001" is only meaningful once the
    // list it would appear in has actually loaded.
    expect((await screen.findAllByText('Beendet')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /TR000001/ })).not.toBeInTheDocument();
  });

  it('drops the open session when the admin signs out', async () => {
    renderApp();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    await screen.findByRole('status');

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));

    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
