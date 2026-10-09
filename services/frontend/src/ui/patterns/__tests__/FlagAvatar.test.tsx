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

  it('shows a given icon instead of the bundled flag', () => {
    renderWithProviders(
      <FlagAvatar
        language={{ code: 'en', native: 'English', english: 'English' }}
        iconUrl="https://studio.example.org/flags/en.svg"
      />
    );

    expect(screen.getByRole('img', { name: 'English' })).toHaveAttribute(
      'src',
      'https://studio.example.org/flags/en.svg'
    );
  });

  it('shows a given icon for a language that otherwise gets the text chip', () => {
    renderWithProviders(
      <FlagAvatar
        language={{ code: 'ku', native: 'Kurmancî', english: 'Kurdish' }}
        iconUrl="https://studio.example.org/flags/ku.svg"
      />
    );

    expect(screen.getByRole('img', { name: 'Kurdish' })).toHaveAttribute(
      'src',
      'https://studio.example.org/flags/ku.svg'
    );
    expect(screen.queryByText('KU')).not.toBeInTheDocument();
  });

  it('keeps the bundled flag when the icon is null', () => {
    renderWithProviders(
      <FlagAvatar language={{ code: 'ar', native: 'العربية', english: 'Arabic' }} iconUrl={null} />
    );

    expect(screen.getByRole('img', { name: 'Arabic' })).toHaveAttribute('src', '/flags/sa.png');
  });
});
