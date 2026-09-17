import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQuery } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
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
    queryFn: () => session.getSession('A1B2C3D4', 'customer'),
  });

  observed.push(query.data?.customerLanguage ?? null);

  return <span data-testid="source-language">{query.data?.customerLanguage ?? 'none'}</span>;
}

const sessionFixture = {
  id: 'A1B2C3D4',
  status: 'active' as const,
  customerLanguage: 'en',
  adminLanguage: 'de',
  createdAt: '2026-08-21T10:00:00+00:00',
  messageCount: 0,
  adminConnected: true,
  customerConnected: true,
};

const route = '/s/A1B2C3D4/info/en';

describe('ConsentScreen', () => {
  it('positions content below the header with the shared content offset', () => {
    renderWithProviders(tree(), { route });

    expect(
      screen.getByText(/Smart Speech Flow is an automatic real-time/).parentElement?.parentElement
        ?.parentElement
    ).toHaveClass('pt-content-top');
  });

  it('shows the chosen language flag', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByRole('img', { name: 'English' })).toBeInTheDocument();
  });

  it('allows continuing without consent', async () => {
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    expect(await screen.findByText('conversation screen')).toBeInTheDocument();
  });

  // One request, not two. A second, consent-less POST to the same endpoint
  // would re-activate the session and resolve its consent to declined,
  // overwriting the answer the guest just gave.
  it('activates exactly once, carrying the checkbox state', async () => {
    const activate = vi.fn().mockResolvedValue(sessionFixture);

    renderWithProviders(tree(), {
      route,
      services: { session: { getSession: vi.fn(), activate } },
    });

    await userEvent.click(await screen.findByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Get started' }));

    await waitFor(() => expect(activate).toHaveBeenCalledTimes(1));
    expect(activate).toHaveBeenCalledWith('A1B2C3D4', 'en', true);
  });

  it('activates once with false when the checkbox is untouched', async () => {
    const activate = vi.fn().mockResolvedValue(sessionFixture);

    renderWithProviders(tree(), {
      route,
      services: { session: { getSession: vi.fn(), activate } },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    await waitFor(() => expect(activate).toHaveBeenCalledTimes(1));
    expect(activate).toHaveBeenCalledWith('A1B2C3D4', 'en', false);
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
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));
    await screen.findByTestId('source-language');

    expect(observed[0]).toBe('en');
    expect(observed).not.toContain(null);
  });
});
