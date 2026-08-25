import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { createStubConsentSink } from '@/domain/consent/StubConsentSink';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
      <Route path="/s/:sessionId/live" element={<p>conversation screen</p>} />
    </Routes>
  );
}

const route = '/s/A1B2C3D4/info/en';

describe('ConsentScreen', () => {
  it('shows the chosen language flag', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByRole('img', { name: 'English' })).toBeInTheDocument();
  });

  it('allows continuing without consent', async () => {
    const recorded = vi.fn();
    renderWithProviders(tree(), {
      route,
      services: { consent: createStubConsentSink(recorded) },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    expect(await screen.findByText('conversation screen')).toBeInTheDocument();
    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: 'A1B2C3D4', dataRetentionConsent: false })
      )
    );
  });

  it('records consent when the box is ticked', async () => {
    const recorded = vi.fn();
    renderWithProviders(tree(), {
      route,
      services: { consent: createStubConsentSink(recorded) },
    });

    await userEvent.click(await screen.findByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Get started' }));

    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith(expect.objectContaining({ dataRetentionConsent: true }))
    );
  });

  it('activates the session with the chosen language before continuing', async () => {
    const activate = vi.fn().mockResolvedValue({
      id: 'A1B2C3D4',
      status: 'active',
      customerLanguage: 'en',
      adminLanguage: 'de',
      createdAt: '2026-08-21T10:00:00+00:00',
      messageCount: 0,
      adminConnected: true,
      customerConnected: true,
    });

    renderWithProviders(tree(), {
      route,
      services: {
        session: {
          getSession: vi.fn(),
          activate,
          reportActivity: vi.fn(),
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    expect(activate).toHaveBeenCalledWith('A1B2C3D4', 'en');
  });
});
