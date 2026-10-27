import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createRealtimeWire } from '@/test/realtimeWire';
import { server } from '@/test/setup';

const SESSION = 'A1B2C3D4';
const body = (state: string, version: number) => ({
  state,
  reason: null,
  window_id: state === 'off' || state === 'asking' ? null : 'w1',
  state_version: version,
  since: new Date().toISOString(),
});
const frame = (state: string, version: number) => ({
  type: 'recording_state',
  role: 'recording_state',
  session_id: SESSION,
  ...body(state, version),
});

function render() {
  const wire = createRealtimeWire();
  renderWithProviders(
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>,
    {
      route: `/s/${SESSION}/live`,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          resolveAudioUrl: (url: string) => url,
        },
        createRealtime: () => wire.transport,
      },
    }
  );
  return wire;
}

afterEach(() => {
  vi.useRealTimers();
});

describe('recording, as the guest sees it', () => {
  it('asks the question and sends the yes with its request id', async () => {
    let answered: unknown;
    server.use(
      http.post(`*/api/customer/session/${SESSION}/recording/answer`, async ({ request }) => {
        answered = await request.json();
        return HttpResponse.json(body('arming', 2));
      })
    );
    const wire = render();
    await screen.findByRole('button', { name: 'Record' });

    await wire.receive(frame('asking', 1));
    await wire.receive({
      type: 'recording_request',
      role: 'recording_request',
      session_id: SESSION,
      request_id: 'r-1',
      consent_kind: 'first',
    });
    expect(await screen.findByRole('dialog')).toHaveTextContent(
      'May this conversation be recorded?'
    );
    expect(wire.transport.send).toHaveBeenCalledWith({
      type: 'recording_state_ack',
      state_version: 1,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Yes, record' }));

    expect(answered).toEqual({ request_id: 'r-1', consent: true });
    expect(await screen.findByText('Recording is starting…')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows the red band and frame only while pings arrive, then pauses on its own', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const wire = render();
    await screen.findByRole('button', { name: 'Record' });
    await wire.status('connected');

    await wire.receive(frame('on', 3));
    await wire.receive({ type: 'recording_ping', role: 'recording_ping', session_id: SESSION });

    expect(await screen.findByText('Recording')).toBeInTheDocument();
    expect(document.querySelector('[data-recording-frame]')).not.toBeNull();
    expect(wire.transport.send).toHaveBeenCalledWith({ type: 'recording_pong' });

    await act(async () => {
      vi.advanceTimersByTime(13_000);
    });

    expect(screen.getByText('Recording paused · connection interrupted')).toBeInTheDocument();
    expect(document.querySelector('[data-recording-frame]')).toBeNull();
  });

  it('stops from the band', async () => {
    const stopped = vi.fn();
    server.use(
      http.post(`*/api/customer/session/${SESSION}/recording/stop`, () => {
        stopped();
        return HttpResponse.json(body('off', 4));
      })
    );
    const wire = render();
    await screen.findByRole('button', { name: 'Record' });
    await wire.status('connected');
    await wire.receive(frame('on', 3));
    await wire.receive({ type: 'recording_ping', role: 'recording_ping', session_id: SESSION });
    expect(await screen.findByText('Recording')).toBeInTheDocument();

    await userEvent.click(await screen.findByRole('button', { name: 'Stop recording' }));

    expect(stopped).toHaveBeenCalledOnce();
    expect(document.querySelector('[data-recording-band]')).toBeNull();
  });

  it('shows a reconnected recording as live on its state alone, before the next ping', async () => {
    const wire = render();
    await screen.findByRole('button', { name: 'Record' });
    await wire.status('connected');

    await wire.receive(frame('on', 3));

    expect(await screen.findByRole('status')).toHaveTextContent('Recording');
    expect(document.querySelector('[data-recording-frame]')).not.toBeNull();
  });

  it('keeps the question open and says so when the yes fails', async () => {
    server.use(
      http.post(`*/api/customer/session/${SESSION}/recording/answer`, () =>
        HttpResponse.json(
          { detail: { error_code: 'RECORDING_POLICY_UNAVAILABLE', message: 'x' } },
          { status: 503 }
        )
      )
    );
    const wire = render();
    await screen.findByRole('button', { name: 'Record' });
    await wire.receive(frame('asking', 1));
    await wire.receive({
      type: 'recording_request',
      role: 'recording_request',
      session_id: SESSION,
      request_id: 'r-1',
      consent_kind: 'resume',
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Yes, record' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Continue recording?');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'The recording could not be changed. Please try again.'
    );
  });
});
