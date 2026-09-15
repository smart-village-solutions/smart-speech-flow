import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';

describe('the admin entry link', () => {
  it('offers only the tenant login chooser from the start page', async () => {
    renderWithProviders(<AccessCodeScreen />, { locale: 'de' });

    expect(await screen.findByRole('link', { name: 'Login' })).toHaveAttribute(
      'href',
      '/login'
    );
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.queryByRole('link', { name: 'Admin-Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Neuer Admin-Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Studio/i })).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/admin"]')).toBeNull();
  });
});
