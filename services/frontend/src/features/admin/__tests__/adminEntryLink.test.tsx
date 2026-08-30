import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';

describe('the admin entry link', () => {
  it('keeps both temporary administrative entrypoints reachable', async () => {
    renderWithProviders(<AccessCodeScreen />, { locale: 'de' });

    expect(await screen.findByRole('link', { name: 'Admin-Login' })).toHaveAttribute(
      'href',
      '/admin'
    );
    expect(screen.getByRole('link', { name: 'Neuer Admin-Login' })).toHaveAttribute(
      'href',
      '/login'
    );
  });
});
