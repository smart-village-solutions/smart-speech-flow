import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';

describe('FlagAvatar', () => {
  it('renders the bundled flag for a language that has one', () => {
    renderWithProviders(
      <FlagAvatar language={{ code: 'ar', native: 'العربية', english: 'Arabic' }} />
    );

    expect(screen.getByRole('img', { name: 'Arabic' })).toHaveAttribute('src', '/flags/sa.png');
  });

  it('falls back to a text chip for a language with no country flag', () => {
    renderWithProviders(
      <FlagAvatar language={{ code: 'ku', native: 'Kurmancî', english: 'Kurdish' }} />
    );

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('KU')).toBeInTheDocument();
  });
});
