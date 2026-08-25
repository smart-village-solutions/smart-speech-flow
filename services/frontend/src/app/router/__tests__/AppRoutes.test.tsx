import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';

describe('AppRoutes', () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it('serves the access-code screen at the root', async () => {
    renderWithProviders(<AppRoutes />, { route: '/' });

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('keeps the legacy landing page reachable at /legacy', async () => {
    renderWithProviders(<AppRoutes />, { route: '/legacy' });

    expect(await screen.findByPlaceholderText('Passwort')).toBeInTheDocument();
  });

  it('sends an unauthenticated /admin visit to the password gate', async () => {
    renderWithProviders(<AppRoutes />, { route: '/admin' });

    expect(await screen.findByPlaceholderText('Passwort')).toBeInTheDocument();
  });

  it('lands on the admin page once the password gate accepts the password', async () => {
    renderWithProviders(<AppRoutes />, { route: '/admin' });

    await userEvent.type(await screen.findByPlaceholderText('Passwort'), 'ssf2025kassel');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));

    expect(
      await screen.findByRole('heading', { name: 'Admin - Session Verwaltung' })
    ).toBeInTheDocument();
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
