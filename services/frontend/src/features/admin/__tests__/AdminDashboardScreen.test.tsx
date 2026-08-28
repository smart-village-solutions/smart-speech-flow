import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';

const noop = () => undefined;

describe('AdminDashboardScreen', () => {
  it('welcomes the SSF tenant', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      brand: 'ssf',
    });
    expect(await screen.findByText('Willkommen bei Smart Speech Flow')).toBeInTheDocument();
  });

  it('welcomes the Kassel tenant', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      brand: 'kassel',
    });
    expect(await screen.findByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
  });

  it('lists the sessions the gateway returned, live one first', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });

    expect(await screen.findByText('Vergangene Gespräche')).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    ).toBeInTheDocument();
  });

  it('warns before a new conversation ends the live one', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />, {
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/AR000001/)).toBeInTheDocument();
  });

  it('shows the system load from the gateway', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />);
    expect(await screen.findByText('Ausreichend Kapazitäten verfügbar')).toBeInTheDocument();
  });

  it('carries the admin header', async () => {
    renderWithProviders(<AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />);
    expect(await screen.findByRole('button', { name: 'Benutzerkonto' })).toBeInTheDocument();
  });
});
