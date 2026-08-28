import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { AppHeader } from '@/ui/patterns/AppHeader';

const noop = () => undefined;

describe('AdminHeader', () => {
  it('carries every customer header control plus the user menu', () => {
    renderWithProviders(
      <AdminHeader onBack={noop} onHome={noop} onFeedback={noop} onSignOut={noop} />,
      { locale: 'de' }
    );

    for (const name of ['Zurück', 'Start', 'Feedback', 'Design wechseln', 'Benutzerkonto']) {
      expect(screen.getByRole('button', { name }), name).toBeInTheDocument();
    }
  });

  it('signs out through the menu', async () => {
    const onSignOut = vi.fn();
    renderWithProviders(
      <AdminHeader onBack={noop} onHome={noop} onFeedback={noop} onSignOut={onSignOut} />,
      { locale: 'de' }
    );

    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });
});

describe('AppHeader', () => {
  it('renders no user menu for the customer', () => {
    renderWithProviders(<AppHeader onBack={noop} onHome={noop} onFeedback={noop} />, {
      locale: 'de',
    });
    expect(screen.queryByRole('button', { name: 'Benutzerkonto' })).not.toBeInTheDocument();
  });
});
