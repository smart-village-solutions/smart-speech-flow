import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';

const noop = () => undefined;

describe('AdminDashboardScreen', () => {
  it('positions the dashboard below the header with the shared content offset', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />);

    expect((await screen.findByText('Willkommen bei KasselDIALOG')).closest('div[class*="pt-"]'))
      .toHaveClass('pt-content-top');
  });

  it('welcomes the SSF tenant', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      brand: 'ssf',
    });
    expect(await screen.findByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
  });

  it('welcomes the Kassel tenant', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      brand: 'kassel',
    });
    expect(await screen.findByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
  });

  it('lists the sessions the gateway returned, live one first', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });

    expect(await screen.findByText('Vergangene Gespräche')).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    ).toBeInTheDocument();
  });

  it('warns before a new conversation ends the live one', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/AR000001/)).toBeInTheDocument();
  });

  // The history lists every admin of the tenant; only the admin's own session ends.
  it("names the admin's own conversation, not a colleague's newer one", async () => {
    server.use(
      http.get('*/api/admin/session/current', () =>
        HttpResponse.json({ session_id: 'DE000001', status: 'active' })
      )
    );
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });
    await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' });

    await userEvent.click(screen.getByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByRole('dialog')).toHaveTextContent('DE000001');
    expect(screen.getByRole('dialog')).not.toHaveTextContent('AR000001');
  });

  it("does not warn when only a colleague's conversation is live", async () => {
    installFakeClipboard();
    server.use(
      http.get('*/api/admin/session/current', () =>
        HttpResponse.json({ detail: 'Keine aktive Admin-Session gefunden' }, { status: 404 })
      )
    );
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });
    await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' });

    await userEvent.click(screen.getByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
    expect(screen.queryByText(/Laufendes Gespräch beenden/)).not.toBeInTheDocument();
  });

  it('shows the system load from the gateway', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />);
    expect(await screen.findByText('Ausreichend Kapazitäten verfügbar')).toBeInTheDocument();
  });

  it('carries the admin header', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />);
    expect(await screen.findByRole('button', { name: 'Benutzerkonto' })).toBeInTheDocument();
  });
});
