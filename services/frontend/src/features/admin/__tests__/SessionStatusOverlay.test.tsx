import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SessionStatusOverlay } from '@/features/admin/SessionStatusOverlay';

const ARABIC = {
  bundled: { code: 'ar', native: 'العربية', english: 'Arabic' },
  name: 'Arabisch',
};

describe('SessionStatusOverlay', () => {
  it('names the session', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByText('A1B2C3D4')).toBeInTheDocument();
  });

  it('reports a live connection', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByRole('status')).toHaveTextContent('Verbunden');
  });

  // A screen that has just mounted is connecting, not disconnected — there is
  // nothing to report as lost yet.
  it('reads a socket that has not opened yet as connecting', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="disconnected" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByRole('status')).toHaveTextContent('Verbindung wird hergestellt');
  });

  it('reads a connecting socket as connecting', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connecting" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByRole('status')).toHaveTextContent('Verbindung wird hergestellt');
  });

  it('reports an exhausted socket as interrupted', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="error" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByRole('status')).toHaveTextContent('Verbindung unterbrochen');
  });

  it('names the customer language in German', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByText('Arabisch')).toBeInTheDocument();
    expect(screen.queryByText('العربية')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Arabic' })).toBeInTheDocument();
  });

  it('names a language SSF does not list without a flag', () => {
    renderWithProviders(
      <SessionStatusOverlay
        sessionId="A1B2C3D4"
        connection="connected"
        language={{ bundled: null, name: 'Suaheli' }}
      />,
      { locale: 'de' }
    );
    expect(screen.getByText('Suaheli')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('omits the language group before anyone has joined', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connecting" language={null} />,
      { locale: 'de' }
    );

    expect(screen.getByText('A1B2C3D4')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
