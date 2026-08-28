import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SessionStatusOverlay } from '@/features/admin/SessionStatusOverlay';

const ARABIC = { code: 'ar', native: 'العربية', english: 'Arabic' };

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

  it('names the customer language', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={ARABIC} />,
      { locale: 'de' }
    );
    expect(screen.getByText('العربية')).toBeInTheDocument();
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
