import { screen } from '@testing-library/react';
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
