import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { readConfig } from '@/app/config/env';
import { AppRoutes } from '@/app/router/AppRoutes';

const services = { config: readConfig({}) };

const signIn = async () => {
  await userEvent.type(await screen.findByLabelText('E-Mail-Adresse'), 'admin@example.com');
  await userEvent.type(screen.getByLabelText('Passwort'), 'ssf2025kassel');
  await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));
};

const renderApp = async () => {
  renderWithProviders(<AppRoutes />, {
    route: '/admin',
    locale: 'de',
    services,
  });

  await signIn();
};

describe('the admin session flow', () => {
  beforeEach(() => sessionStorage.clear());

  it('creates a session, hands out the invite, and enters the conversation', async () => {
    installFakeClipboard();
    await renderApp();

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

  it('re-enters a session that is still open', async () => {
    await renderApp();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );

    expect(await screen.findByRole('status')).toHaveTextContent('AR000001');
  });

  it('leaves a completed session alone', async () => {
    await renderApp();

    // Waiting on the rows, not the heading: the heading renders before the
    // query answers, and "no button for TR000001" is only meaningful once the
    // list it would appear in has actually loaded.
    expect((await screen.findAllByText('abgeschlossen')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /TR000001/ })).not.toBeInTheDocument();
  });

  it('drops the open session when the admin signs out', async () => {
    await renderApp();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    await screen.findByRole('status');

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));

    // Signing out returns to the legacy admin login and drops the active session.
    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
