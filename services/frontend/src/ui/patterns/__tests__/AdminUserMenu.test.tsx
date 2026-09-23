import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminUserMenu } from '@/ui/patterns/AdminUserMenu';

const ACCOUNT_URL =
  'https://auth.dialog.kassel.de/realms/smartcity/account?referrer=ssf-frontend&referrer_uri=https%3A%2F%2Fdialog.kassel.de%2Flogin%2Ftenant-kassel';

const open = () => userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));

describe('AdminUserMenu', () => {
  it('opens and closes on the trigger', async () => {
    renderWithProviders(<AdminUserMenu onSignOut={vi.fn()} />, { locale: 'de' });

    expect(screen.queryByRole('button', { name: 'Abmelden' })).not.toBeInTheDocument();
    await open();
    expect(screen.getByRole('button', { name: 'Abmelden' })).toBeInTheDocument();
    await open();
    expect(screen.queryByRole('button', { name: 'Abmelden' })).not.toBeInTheDocument();
  });

  it('links to the Keycloak account console first, in a new tab', async () => {
    renderWithProviders(
      <AdminUserMenu
        onSignOut={vi.fn()}
        accountUrl={ACCOUNT_URL}
        studioUrl="https://smartcity.dialog.kassel.de/"
      />,
      { locale: 'de' }
    );
    await open();

    const account = screen.getByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' });
    expect(account).toHaveAttribute('href', ACCOUNT_URL);
    expect(account).toHaveAttribute('target', '_blank');
    expect(account).toHaveAttribute('rel', 'noreferrer');
    expect(
      account.compareDocumentPosition(
        screen.getByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })
      )
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it.each([
    'Kontoeinstellungen (öffnet in neuem Tab)',
    'Organisation verwalten (öffnet in neuem Tab)',
  ])('closes once %s has opened its tab', async (name) => {
    renderWithProviders(
      <AdminUserMenu
        onSignOut={vi.fn()}
        accountUrl={ACCOUNT_URL}
        studioUrl="https://smartcity.dialog.kassel.de/"
      />,
      { locale: 'de' }
    );
    await open();

    const link = screen.getByRole('link', { name });
    // jsdom cannot open tabs; the menu only has to react to the click.
    link.addEventListener('click', (event) => event.preventDefault());
    await userEvent.click(link);
    expect(screen.queryByRole('button', { name: 'Abmelden' })).not.toBeInTheDocument();
  });

  it('tells assistive technology that each link opens a new tab', async () => {
    renderWithProviders(
      <AdminUserMenu
        onSignOut={vi.fn()}
        accountUrl={ACCOUNT_URL}
        studioUrl="https://smartcity.dialog.kassel.de/"
      />,
      { locale: 'de' }
    );
    await open();

    for (const name of ['Kontoeinstellungen', 'Organisation verwalten']) {
      const link = screen.getByRole('link', { name: `${name} (öffnet in neuem Tab)` });
      expect(within(link).getByText('(öffnet in neuem Tab)')).toHaveClass('sr-only');
    }
  });

  it('does not show account settings without an account console', async () => {
    renderWithProviders(<AdminUserMenu onSignOut={vi.fn()} />, { locale: 'de' });
    await open();
    expect(
      screen.queryByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' })
    ).not.toBeInTheDocument();
  });

  it('never collects a password or an email address itself', async () => {
    const { container } = renderWithProviders(
      <AdminUserMenu onSignOut={vi.fn()} accountUrl={ACCOUNT_URL} />,
      { locale: 'de' }
    );
    await open();
    expect(container.querySelector('input, form')).toBeNull();
    expect(screen.queryByText('Passwort ändern')).not.toBeInTheDocument();
    expect(screen.queryByText('E-Mail-Adresse ändern')).not.toBeInTheDocument();
  });

  it('signs out', async () => {
    const onSignOut = vi.fn();
    renderWithProviders(<AdminUserMenu onSignOut={onSignOut} />, { locale: 'de' });
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it('shows the Studio link before sign-out when supplied', async () => {
    renderWithProviders(
      <AdminUserMenu onSignOut={vi.fn()} studioUrl="https://smartcity.dialog.kassel.de/" />,
      { locale: 'de' }
    );

    await open();

    const studio = screen.getByRole('link', {
      name: 'Organisation verwalten (öffnet in neuem Tab)',
    });
    expect(studio).toHaveAttribute('href', 'https://smartcity.dialog.kassel.de/');
    expect(studio).toHaveAttribute('target', '_blank');
    expect(studio.compareDocumentPosition(screen.getByRole('button', { name: 'Abmelden' }))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it('does not show the Studio link when it is not supplied', async () => {
    renderWithProviders(<AdminUserMenu onSignOut={vi.fn()} />, { locale: 'de' });
    await open();
    expect(
      screen.queryByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })
    ).not.toBeInTheDocument();
  });

  it('uses compact text for all menu actions', async () => {
    renderWithProviders(
      <AdminUserMenu
        onSignOut={vi.fn()}
        accountUrl={ACCOUNT_URL}
        studioUrl="https://smartcity.dialog.kassel.de/"
      />,
      { locale: 'de' }
    );
    await open();

    expect(
      screen.getByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' })
    ).toHaveClass('text-note');
    expect(
      screen.getByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })
    ).toHaveClass('text-note');
    expect(screen.getByRole('button', { name: 'Abmelden' })).toHaveClass('text-note');
  });

  it('lets the panel draw a divider between rows, never the rows themselves', async () => {
    renderWithProviders(
      <AdminUserMenu
        onSignOut={vi.fn()}
        accountUrl={ACCOUNT_URL}
        studioUrl="https://smartcity.dialog.kassel.de/"
      />,
      { locale: 'de' }
    );
    await open();

    const signOut = screen.getByRole('button', { name: 'Abmelden' });
    expect(signOut.parentElement).toHaveClass('divide-y', 'divide-border-divider');
    for (const row of [
      screen.getByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' }),
      screen.getByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' }),
      signOut,
    ]) {
      expect(row.className).not.toMatch(/\bborder-t\b/);
    }
  });

  it('closes on a tap outside the menu', async () => {
    renderWithProviders(
      <div>
        <AdminUserMenu onSignOut={vi.fn()} />
        <button type="button">elsewhere</button>
      </div>,
      { locale: 'de' }
    );

    await open();
    expect(screen.getByRole('button', { name: 'Abmelden' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }));
    expect(screen.queryByRole('button', { name: 'Abmelden' })).not.toBeInTheDocument();
  });
});
