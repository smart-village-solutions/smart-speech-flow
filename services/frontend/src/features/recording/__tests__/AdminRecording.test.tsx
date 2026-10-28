import { screen, within } from '@testing-library/react';
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
const askable = {
  ...off,
  can_request: true,
  unavailable_reason: null,
  next_consent_kind: 'first',
  id_check: 'optional',
};

function render(view: Record<string, unknown>) {
  server.use(http.get(`*/api/admin/session/${SESSION}/recording`, () => HttpResponse.json(view)));
  const wire = createRealtimeWire();
  renderWithProviders(
    <AdminSessionScreen sessionId={SESSION} onLeave={vi.fn()} onSignOut={vi.fn()} />,
    { locale: 'de', services: { createRealtime: () => wire.transport } }
  );
  return wire;
}

describe('recording, as the employee sees it', () => {
  it('asks for the name and ID check before a first request, then sends it with a fresh id', async () => {
    let requested: Record<string, unknown> = {};
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, async ({ request }) => {
        requested = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...off, state: 'asking', state_version: 1 });
      })
    );
    render(askable);

    expect(await screen.findByText('Keine Aufnahme')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Name des Gastes (freiwillig)'), ' Amira ');
    await userEvent.click(within(dialog).getByText('Identität mit Ausweisdokument geprüft'));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Aufnahme anfragen' }));

    expect(requested.request_id).toMatch(/^[0-9a-f-]{32,36}$/);
    expect(requested).toMatchObject({ guest_name: 'Amira', id_checked: true });
    expect(await screen.findByText('Warten auf die Antwort des Gastes …')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anfrage zurückziehen' })).toBeInTheDocument();
  });

  it('holds a first request back until a required ID check is ticked', async () => {
    render({ ...askable, id_check: 'required' });

    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    const send = within(dialog).getByRole('button', { name: 'Aufnahme anfragen' });

    expect(send).toBeDisabled();
    await userEvent.click(within(dialog).getByText('Identität mit Ausweisdokument geprüft'));
    expect(send).toBeEnabled();
  });

  it('sends a first request once, however often it is clicked', async () => {
    const requested = vi.fn();
    let answer = () => {};
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, async () => {
        requested();
        await new Promise<void>((resolve) => (answer = resolve));
        return HttpResponse.json({ ...off, state: 'asking', state_version: 1 });
      })
    );
    render(askable);

    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    const send = within(dialog).getByRole('button', { name: 'Aufnahme anfragen' });
    await userEvent.click(send);
    await userEvent.click(send);

    expect(send).toBeDisabled();
    answer();
    expect(await screen.findByText('Warten auf die Antwort des Gastes …')).toBeInTheDocument();
    expect(requested).toHaveBeenCalledOnce();
  });

  it('requests a resume straight from the band', async () => {
    let requested: Record<string, unknown> = {};
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, async ({ request }) => {
        requested = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...off, state: 'asking', state_version: 1 });
      })
    );
    render({ ...askable, next_consent_kind: 'resume' });

    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));

    expect(await screen.findByText('Warten auf die Antwort des Gastes …')).toBeInTheDocument();
    expect(Object.keys(requested)).toEqual(['request_id']);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
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
    render(askable);

    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Aufnahme anfragen' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Der Gast ist nicht verbunden.'
    );
  });

  it("says so when the guest's yes could not be recorded", async () => {
    const wire = render(askable);
    await screen.findByText('Keine Aufnahme');

    await wire.receive({
      type: 'recording_error',
      role: 'recording_error',
      session_id: SESSION,
      code: 'ARCHIVE_WRITE_FAILED',
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Die Zustimmung des Gastes konnte nicht gespeichert werden.'
    );
  });

  it('shows no band to an employee who may not ask', async () => {
    render({ ...off, can_request: false, unavailable_reason: 'PERMISSION_REQUIRED' });
    await screen.findByText('A1B2C3D4');
    expect(document.querySelector('[data-recording-band]')).toBeNull();
  });
});
