import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQuery } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { createStubConsentSink } from '@/domain/consent/StubConsentSink';
import { useServices } from '@/app/providers/services';

function tree(live: React.ReactNode = <p>conversation screen</p>) {
  return (
    <Routes>
      <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
      <Route path="/s/:sessionId/live" element={live} />
    </Routes>
  );
}

/**
 * Stands in for the conversation screen, which reads the same cache entry the
 * route guard filled before activation. What matters is the first value it
 * sees: a send in that window goes out under the wrong source language.
 */
function SessionLanguage({ observed }: Readonly<{ observed: (string | null)[] }>) {
  const { session } = useServices();
  const query = useQuery({
    queryKey: ['session', 'A1B2C3D4'],
    queryFn: () => session.getSession('A1B2C3D4'),
  });

  observed.push(query.data?.customerLanguage ?? null);

  return <span data-testid="source-language">{query.data?.customerLanguage ?? 'none'}</span>;
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

  // The route guard has already cached the session as it was before activation,
  // where the customer's language is still null. Landing on the conversation
  // with that entry sends the first message under the wrong source language,
  // which the gateway rejects with a 400.
  it('publishes the activated session, so the next screen never sees the stale one', async () => {
    const preActivation = {
      id: 'A1B2C3D4',
      status: 'pending' as const,
      customerLanguage: null,
      adminLanguage: 'de',
      createdAt: '2026-08-21T10:00:00+00:00',
      messageCount: 0,
      adminConnected: true,
      customerConnected: false,
    };
    const activated = { ...preActivation, status: 'active' as const, customerLanguage: 'en' };
    const observed: (string | null)[] = [];

    renderWithProviders(tree(<SessionLanguage observed={observed} />), {
      route,
      services: {
        session: {
          // Any read after activation sees the activated session, as the
          // gateway reports it. The stale one is the entry already cached.
          getSession: vi.fn().mockResolvedValue(activated),
          activate: vi.fn().mockResolvedValue(activated),
          reportActivity: vi.fn(),
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));
    await screen.findByTestId('source-language');

    expect(observed[0]).toBe('en');
    expect(observed).not.toContain(null);
  });
});
