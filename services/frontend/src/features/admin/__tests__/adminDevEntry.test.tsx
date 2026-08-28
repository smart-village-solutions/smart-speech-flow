import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import { readConfig } from '@/app/config/env';

const servicesWith = (adminDevEntry: boolean) => ({
  config: { ...readConfig({}), adminDevEntry },
});

const signIn = async () => {
  await userEvent.type(await screen.findByLabelText('E-Mail-Adresse'), 'admin@example.com');
  await userEvent.type(screen.getByLabelText('Passwort'), 'ssf2025kassel');
  await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));
};

describe('the admin entry', () => {
  beforeEach(() => sessionStorage.clear());

  it('serves the new UI at /admin without any flag', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    expect(await screen.findByRole('heading', { name: 'Anmelden' })).toBeInTheDocument();
  });

  it('reaches the dashboard through the password', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    await signIn();

    expect(await screen.findByText('Willkommen bei Smart Speech Flow')).toBeInTheDocument();
  });

  it('stays on the login when the password is wrong', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    await userEvent.type(await screen.findByLabelText('E-Mail-Adresse'), 'admin@example.com');
    await userEvent.type(screen.getByLabelText('Passwort'), 'nope');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Ungültige Anmeldedaten.');
    expect(screen.queryByText('Willkommen bei Smart Speech Flow')).not.toBeInTheDocument();
  });

  it('skips the login at /admin/dev when the flag is set', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin/dev',
      locale: 'de',
      services: servicesWith(true),
    });

    expect(await screen.findByText('Willkommen bei Smart Speech Flow')).toBeInTheDocument();
  });

  it('does not serve /admin/dev when the flag is off', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin/dev',
      locale: 'de',
      services: servicesWith(false),
    });

    expect(await screen.findByText('404')).toBeInTheDocument();
  });

  it('keeps the legacy admin page reachable at /legacy/admin', async () => {
    sessionStorage.setItem('authenticated', 'true');
    renderWithProviders(<AppRoutes />, {
      route: '/legacy/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    expect(await screen.findByText('Admin - Session Verwaltung')).toBeInTheDocument();
  });

  // The export has one `goHome` for every screen and it returns to the OTP
  // screen (App.tsx:1621), which is our access-code screen. Home is the way out
  // of the admin UI, not a link back into it.
  it('leaves the admin UI for the access-code screen from the dashboard', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    await signIn();
    await screen.findByText('Willkommen bei Smart Speech Flow');

    await userEvent.click(screen.getByRole('button', { name: 'Start' }));

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('leaves the admin UI for the access-code screen from a conversation', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin/dev',
      locale: 'de',
      services: servicesWith(true),
    });

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    await screen.findByRole('status');

    await userEvent.click(screen.getByRole('button', { name: 'Start' }));

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('signs out to the access-code screen and forgets the password', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      locale: 'de',
      services: servicesWith(false),
    });

    await signIn();
    await screen.findByText('Willkommen bei Smart Speech Flow');

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
    // Landing on the right screen is not proof the gate reopened: the flag is
    // what a later visit to /admin reads.
    expect(sessionStorage.getItem('authenticated')).toBeNull();
  });

  it('keeps the chosen theme across navigation within the admin session', async () => {
    renderWithProviders(<AppRoutes />, {
      route: '/admin',
      theme: 'dark',
      locale: 'de',
      services: servicesWith(false),
    });

    await signIn();
    await screen.findByText('Willkommen bei Smart Speech Flow');
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Design wechseln' }));
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    // Signing out crosses out of the admin UI into the customer entry screen,
    // which is a harder test of the theme surviving than the login screen was.
    await screen.findByRole('heading', { name: 'Code eingeben' });

    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
