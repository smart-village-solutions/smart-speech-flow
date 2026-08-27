import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RequireSession } from '@/app/router/RequireSession';

function tree() {
  return (
    <Routes>
      <Route path="/" element={<p>access code</p>} />
      <Route path="/s/:sessionId" element={<RequireSession />}>
        <Route index element={<p>inside</p>} />
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
    server.use(http.get('*/api/session/ZZZZZZZZ', () => new HttpResponse(null, { status: 404 })));

    renderWithProviders(tree(), { route: '/s/ZZZZZZZZ' });

    await waitFor(() => expect(screen.getByText('access code')).toBeInTheDocument());
  });

  it('sends a terminated session back to the access-code screen', async () => {
    server.use(
      http.get('*/api/session/A1B2C3D4', () =>
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
});
