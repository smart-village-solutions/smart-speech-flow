import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import { requireKeycloakLogin, logoutFromKeycloak } from '@/app/auth/keycloak';

vi.mock('@/app/auth/keycloak', () => ({
  requireKeycloakLogin: vi.fn(),
  logoutFromKeycloak: vi.fn(),
  getAdminAccessToken: vi.fn().mockResolvedValue('tenant-token'),
}));

const kassel = { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' };
function Location() {
  return <output aria-label="Location">{useLocation().pathname}</output>;
}

describe('tenant login routes', () => {
  beforeEach(() => {
    vi.mocked(requireKeycloakLogin).mockReset().mockResolvedValue(true);
    vi.mocked(logoutFromKeycloak).mockReset().mockResolvedValue(undefined);
    sessionStorage.clear();
  });

  it('shows the chooser without initializing Keycloak', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login' });
    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toHaveAttribute(
      'href',
      '/login/tenant-kassel'
    );
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('resolves the full directory entry and shows the dashboard on the tenant callback', async () => {
    renderWithProviders(
      <>
        <AppRoutes />
        <Location />
      </>,
      { route: '/login/tenant-kassel?realm=evil' }
    );
    expect(
      await screen.findByRole('button', { name: 'Neues Gespräch starten' })
    ).toBeInTheDocument();
    expect(requireKeycloakLogin).toHaveBeenCalledWith(expect.any(Object), kassel);
    expect(screen.getByLabelText('Location')).toHaveTextContent('/login/tenant-kassel');
  });

  it('does not render the dashboard while Keycloak redirects', async () => {
    vi.mocked(requireKeycloakLogin).mockResolvedValue(false);
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled());
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
  });

  it('rejects unknown IDs without interpreting them as realms', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/kassel-ssf-2025' });
    expect(await screen.findByText(/404/)).toBeInTheDocument();
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('uses the router-decoded ID exactly once', async () => {
    const tenant = { ...kassel, id: 'tenant:kassel' };
    renderWithProviders(<AppRoutes />, {
      route: '/login/tenant%3Akassel',
      services: { loginTenant: { list: async () => [tenant] } },
    });
    await waitFor(() =>
      expect(requireKeycloakLogin).toHaveBeenCalledWith(expect.any(Object), tenant)
    );
  });

  it.each(['directory', 'authentication'])('fails neutrally on %s errors', async (source) => {
    if (source === 'authentication')
      vi.mocked(requireKeycloakLogin).mockRejectedValue(new Error('private details'));
    renderWithProviders(<AppRoutes />, {
      route: '/login/tenant-kassel',
      services: {
        loginTenant: {
          list: async () => {
            if (source === 'directory') throw new Error('private details');
            return [kassel];
          },
        },
      },
    });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('private details')).not.toBeInTheDocument();
    if (source === 'directory') expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('returns to the chooser on logout', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toBeInTheDocument();
    expect(logoutFromKeycloak).toHaveBeenCalledOnce();
  });

  it('cannot expose a previous dashboard after navigating to an unknown tenant', async () => {
    renderWithProviders(
      <>
        <AppRoutes />
        <Link to="/login/unknown">Unknown tenant</Link>
      </>,
      { route: '/login/tenant-kassel' }
    );
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('link', { name: 'Unknown tenant' }));
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('ignores authentication completion after leaving the tenant route', async () => {
    let finish!: (value: boolean) => void;
    vi.mocked(requireKeycloakLogin).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    renderWithProviders(
      <>
        <AppRoutes />
        <Link to="/login/unknown">Unknown tenant</Link>
      </>,
      { route: '/login/tenant-kassel' }
    );
    await waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('link', { name: 'Unknown tenant' }));
    await act(async () => finish(true));
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
  });

  it('keeps the legacy password screen isolated at /admin', async () => {
    renderWithProviders(<AppRoutes />, { route: '/admin' });
    expect(await screen.findByLabelText('Passwort')).toBeInTheDocument();
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });
});

describe('AppRoutes', () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it('serves the access-code screen at the root', async () => {
    renderWithProviders(<AppRoutes />, { route: '/' });

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('renders the not-found page for the removed legacy landing route', async () => {
    renderWithProviders(<AppRoutes />, { route: '/legacy' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('renders the not-found page for the removed legacy admin route', async () => {
    renderWithProviders(<AppRoutes />, { route: '/legacy/admin' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('renders the not-found page for an unknown path', async () => {
    renderWithProviders(<AppRoutes />, { route: '/nowhere' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('sends a QR deep link straight to the language picker', async () => {
    renderWithProviders(<AppRoutes />, { route: '/join/A1B2C3D4' });

    expect(
      await screen.findByRole('heading', { name: 'Choose your language' })
    ).toBeInTheDocument();
  });
});
