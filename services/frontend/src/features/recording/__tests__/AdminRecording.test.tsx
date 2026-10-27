import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createRealtimeWire } from '@/test/realtimeWire';
import { server } from '@/test/setup';

const SESSION = 'A1B2C3D4';
const off = {
  state: 'off',
  reason: null,
  window_id: null,
  state_version: 0,
  since: null,
};

function render(view: Record<string, unknown>) {
  server.use(http.get(`*/api/admin/session/${SESSION}/recording`, () => HttpResponse.json(view)));
  renderWithProviders(
    <AdminSessionScreen sessionId={SESSION} onLeave={vi.fn()} onSignOut={vi.fn()} />,
    { locale: 'de', services: { createRealtime: () => createRealtimeWire().transport } }
  );
}

describe('recording, as the employee sees it', () => {
  it('offers the request and sends it with a fresh id', async () => {
    let requested: { request_id?: string } = {};
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, async ({ request }) => {
        requested = (await request.json()) as { request_id: string };
        return HttpResponse.json({ ...off, state: 'asking', state_version: 1 });
      })
    );
    render({ ...off, can_request: true, unavailable_reason: null });

    expect(await screen.findByText('Keine Aufnahme')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Aufnahme anfragen' }));

    expect(requested.request_id).toMatch(/^[0-9a-f-]{32,36}$/);
    expect(await screen.findByText('Warten auf die Antwort des Gastes …')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anfrage zurückziehen' })).toBeInTheDocument();
  });

  it('names the reason when the gateway refuses', async () => {
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, () =>
        HttpResponse.json(
          { detail: { error_code: 'GUEST_NOT_CONNECTED', message: 'Recording cannot start' } },
          { status: 409 }
        )
      )
    );
    render({ ...off, can_request: true, unavailable_reason: null });

    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Der Gast ist nicht verbunden.');
  });

  it('shows no band to an employee who may not ask', async () => {
    render({ ...off, can_request: false, unavailable_reason: 'PERMISSION_REQUIRED' });
    await screen.findByText('A1B2C3D4');
    expect(document.querySelector('[data-recording-band]')).toBeNull();
  });
});
