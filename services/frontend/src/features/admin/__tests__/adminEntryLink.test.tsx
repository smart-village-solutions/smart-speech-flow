import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';

describe('the admin entry link', () => {
  it('offers only the tenant login chooser from the start page', async () => {
    renderWithProviders(<AccessCodeScreen />, { locale: 'de' });

    // The Studio label; the bundled one is "Login".
    expect(await screen.findByRole('link', { name: 'Login für Nutzer' })).toHaveAttribute(
      'href',
      '/login'
    );
    const legal = screen.queryByRole('navigation', { name: 'Rechtliches' });
    const outsideLegal = screen.getAllByRole('link').filter((link) => !legal?.contains(link));
    expect(outsideLegal).toHaveLength(1);
    expect(screen.queryByRole('link', { name: 'Admin-Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Neuer Admin-Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Studio/i })).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/admin"]')).toBeNull();
  });
});
