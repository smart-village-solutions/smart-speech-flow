import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import { readConfig } from '@/app/config/env';

vi.mock('@/app/auth/keycloak', () => ({
  requireKeycloakLogin: vi.fn().mockResolvedValue(true),
  getAdminAccessToken: vi.fn().mockResolvedValue('tenant-token'),
  getStudioUrlForSystemAdmin: vi.fn().mockReturnValue(null),
  logoutFromKeycloak: vi.fn().mockResolvedValue(undefined),
  subscribeToKeycloakExpiration: () => () => {},
}));

const services = { config: readConfig({}) };

const renderAdmin = () =>
  renderWithProviders(<AppRoutes />, {
    route: '/login/tenant-kassel',
    theme: 'dark',
    locale: 'de',
    services,
  });

describe('the admin entry', () => {
  beforeEach(() => sessionStorage.clear());

  it.each(['/admin', '/admin/dev', '/legacy/admin'])('does not serve %s', async (route) => {
    renderWithProviders(<AppRoutes />, { route, locale: 'de', services });

    expect(await screen.findByText('404')).toBeInTheDocument();
    expect(screen.queryByLabelText('Passwort')).not.toBeInTheDocument();
  });

  // The export has one `goHome` for every screen and it returns to the OTP
  // screen (App.tsx:1621), which is our access-code screen. Home is the way out
  // of the admin UI, not a link back into it.
  it('leaves the admin UI for the access-code screen from the dashboard', async () => {
    renderAdmin();
    await screen.findByText('Willkommen bei Smart Speech Flow');

    await userEvent.click(screen.getByRole('button', { name: 'Start' }));

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('leaves the admin UI for the access-code screen from a conversation', async () => {
    renderAdmin();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    await screen.findByRole('status');

    await userEvent.click(screen.getByRole('button', { name: 'Start' }));

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('keeps the chosen theme across navigation within the admin session', async () => {
    renderAdmin();
    await screen.findByText('Willkommen bei Smart Speech Flow');
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Design wechseln' }));
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    // Signing out crosses out of the admin UI into the tenant chooser, which is
    // a harder test of the theme surviving than staying on one screen.
    await screen.findByRole('link', { name: 'Stadt Kassel' });

    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
