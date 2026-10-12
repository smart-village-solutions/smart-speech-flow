import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RequireSession } from '@/app/router/RequireSession';

/** Inside the guard: re-reads the session, as a language change does. */
function Refresher() {
  const queryClient = useQueryClient();
  return (
    <button
      type="button"
      onClick={() => void queryClient.invalidateQueries({ queryKey: ['session', 'A1B2C3D4'] })}
    >
      refresh
    </button>
  );
}

function tree() {
  return (
    <Routes>
      <Route path="/" element={<p>access code</p>} />
      <Route path="/s/:sessionId" element={<RequireSession />}>
        <Route
          index
          element={
            <>
              <p>inside</p>
              <Refresher />
            </>
          }
        />
      </Route>
    </Routes>
  );
}

describe('RequireSession', () => {
  it('renders the child route for a joinable session', async () => {
    renderWithProviders(tree(), { route: '/s/A1B2C3D4' });

    expect(await screen.findByText('inside')).toBeInTheDocument();
  });

  it('sends an unknown session back to the access-code screen', async () => {
    server.use(
      http.get('*/api/customer/session/ZZZZZZZZ', () => new HttpResponse(null, { status: 404 }))
    );

    renderWithProviders(tree(), { route: '/s/ZZZZZZZZ' });

    await waitFor(() => expect(screen.getByText('access code')).toBeInTheDocument());
  });

  it('sends a terminated session back to the access-code screen', async () => {
    server.use(
      http.get('*/api/customer/session/A1B2C3D4', () =>
        HttpResponse.json({
          id: 'A1B2C3D4',
          customer_language: 'en',
          admin_language: 'de',
          status: 'terminated',
          created_at: '2026-08-21T10:00:00+00:00',
          message_count: 0,
          admin_connected: false,
          customer_connected: false,
        })
      )
    );

    renderWithProviders(tree(), { route: '/s/A1B2C3D4' });

    await waitFor(() => expect(screen.getByText('access code')).toBeInTheDocument());
  });

  it('keeps a live conversation when a re-read fails on a network blip', async () => {
    renderWithProviders(tree(), { route: '/s/A1B2C3D4' });
    await screen.findByText('inside');

    server.use(http.get('*/api/customer/session/A1B2C3D4', () => HttpResponse.error()));
    await userEvent.click(screen.getByRole('button', { name: 'refresh' }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(screen.getByText('inside')).toBeInTheDocument();
  });

  it('still leaves when a re-read says the conversation is gone', async () => {
    renderWithProviders(tree(), { route: '/s/A1B2C3D4' });
    await screen.findByText('inside');

    server.use(
      http.get('*/api/customer/session/A1B2C3D4', () => new HttpResponse(null, { status: 404 }))
    );
    await userEvent.click(screen.getByRole('button', { name: 'refresh' }));

    await waitFor(() => expect(screen.getByText('access code')).toBeInTheDocument());
  });
});
