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

  it('reviews a fresh employee release for a resume and sends only its digest', async () => {
    let requested: Record<string, unknown> | null = null;
    const release = {
      language: 'de',
      html: '<h2>Section release</h2><p>Employee wording.</p>',
      accept_label: 'Release section',
      decline_label: 'Cancel section',
      sha256: 'a'.repeat(64),
    };
    server.use(
      http.post(`*/api/admin/session/${SESSION}/recording/request`, async ({ request }) => {
        requested = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...off, state: 'asking', state_version: 1 });
      })
    );
    render({ ...askable, next_consent_kind: 'resume', staff_release: release });
    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Employee wording.')).toBeInTheDocument();
    expect(within(dialog).queryByLabelText('Name des Gastes (freiwillig)')).toBeNull();
    expect(requested).toBeNull();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Release section' }));
    await vi.waitFor(() =>
      expect(requested).toMatchObject({ staff_release_sha256: release.sha256 })
    );
    expect(Object.keys(requested!)).toEqual(['request_id', 'staff_release_sha256']);
  });

  it('identifies source-language employee wording on the German staff screen', async () => {
    render({
      ...askable,
      next_consent_kind: 'resume',
      staff_release: {
        language: 'en',
        html: '<p>Source employee release</p>',
        accept_label: 'Release section',
        decline_label: 'Dismiss',
        sha256: 'a'.repeat(64),
      },
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Aufnahme anfragen' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Originalsprache: en')).toBeInTheDocument();
    expect(within(dialog).getByText('Source employee release').closest('[lang]')).toHaveAttribute(
      'lang',
      'en'
    );
    expect(within(dialog).getByRole('button', { name: 'Release section' })).toHaveAttribute(
      'lang',
      'en'
    );
  });

  it('refetches the release when reopening and cancels without a recording request', async () => {
    const release = {
      language: 'de',
      html: '<p>Old release</p>',
      accept_label: 'Release',
      decline_label: 'Dismiss release',
      sha256: 'a'.repeat(64),
    };
    render({ ...askable, staff_release: release });
    await screen.findByRole('button', { name: 'Aufnahme anfragen' });
    server.use(
      http.get(`*/api/admin/session/${SESSION}/recording`, () =>
        HttpResponse.json({
          ...askable,
          staff_release: { ...release, html: '<p>Updated release</p>' },
        })
      )
    );
    await userEvent.click(screen.getByRole('button', { name: 'Aufnahme anfragen' }));
    expect(await screen.findByText('Updated release')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss release' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText('Keine Aufnahme')).toBeInTheDocument();
  });

  it('reloads changed employee wording before a retry', async () => {
    let changed = false;
    const release = {
      language: 'de',
      html: '<p>Original release</p>',
      accept_label: 'Release',
      decline_label: 'Dismiss',
      sha256: 'a'.repeat(64),
    };
    render({ ...askable, staff_release: release });
    await screen.findByRole('button', { name: 'Aufnahme anfragen' });
    server.use(
      http.get(`*/api/admin/session/${SESSION}/recording`, () =>
        HttpResponse.json({
          ...askable,
          staff_release: { ...release, html: changed ? '<p>Changed release</p>' : release.html },
        })
      ),
      http.post(`*/api/admin/session/${SESSION}/recording/request`, () => {
        changed = true;
        return HttpResponse.json(
          { detail: { error_code: 'STAFF_RELEASE_TEXT_MISMATCH' } },
          { status: 409 }
        );
      })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Aufnahme anfragen' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Release' }));
    expect(await screen.findByText('Changed release')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Text');
  });

  it('holds retry back when changed employee wording cannot be reloaded', async () => {
    let changed = false;
    const release = {
      language: 'de',
      html: '<p>Review release</p>',
      accept_label: 'Release',
      decline_label: 'Dismiss',
      sha256: 'a'.repeat(64),
    };
    render({ ...askable, staff_release: release });
    await screen.findByRole('button', { name: 'Aufnahme anfragen' });
    server.use(
      http.get(`*/api/admin/session/${SESSION}/recording`, () =>
        changed
          ? new HttpResponse(null, { status: 503 })
          : HttpResponse.json({ ...askable, staff_release: release })
      ),
      http.post(`*/api/admin/session/${SESSION}/recording/request`, () => {
        changed = true;
        return HttpResponse.json(
          { detail: { error_code: 'STAFF_RELEASE_TEXT_MISMATCH' } },
          { status: 409 }
        );
      })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Aufnahme anfragen' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Release' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Aufnahme');
    expect(screen.getByRole('button', { name: 'Release' })).toBeDisabled();
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
