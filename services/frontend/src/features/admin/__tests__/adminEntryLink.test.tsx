import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';

describe('the admin entry link', () => {
  it('points at the new admin UI whatever the flag says', async () => {
    renderWithProviders(<AccessCodeScreen />, { locale: 'de' });

    expect(await screen.findByRole('link', { name: 'Admin-Login' })).toHaveAttribute(
      'href',
      '/admin'
    );
  });
});
