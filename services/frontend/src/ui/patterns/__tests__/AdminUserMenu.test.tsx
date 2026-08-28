import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminUserMenu } from '@/ui/patterns/AdminUserMenu';

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

  it('shows only one form at a time', async () => {
    renderWithProviders(<AdminUserMenu onSignOut={vi.fn()} />, { locale: 'de' });
    await open();

    await userEvent.click(screen.getByRole('button', { name: 'Passwort ändern' }));
    expect(screen.getByLabelText('Neues Passwort')).toBeInTheDocument();
    expect(screen.getByLabelText('Bestätigen')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'E-Mail-Adresse ändern' }));
    expect(screen.getByLabelText('Neue E-Mail-Adresse')).toBeInTheDocument();
    expect(screen.queryByLabelText('Neues Passwort')).not.toBeInTheDocument();
  });

  it('collapses a form when its own row is tapped again', async () => {
    renderWithProviders(<AdminUserMenu onSignOut={vi.fn()} />, { locale: 'de' });
    await open();

    const row = screen.getByRole('button', { name: 'Passwort ändern' });
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');

    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Neues Passwort')).not.toBeInTheDocument();
  });

  it('signs out', async () => {
    const onSignOut = vi.fn();
    renderWithProviders(<AdminUserMenu onSignOut={onSignOut} />, { locale: 'de' });
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(onSignOut).toHaveBeenCalledOnce();
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
