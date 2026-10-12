import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { AppError } from '@/core/http/AppError';
import { clockTime } from '@/lib/sessionTimes';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createRealtimeWire } from '@/test/realtimeWire';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';

const route = '/s/A1B2C3D4/live';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>
  );
}

function render(
  wire: ReturnType<typeof createRealtimeWire>,
  { sendText = vi.fn(), getHistory = vi.fn().mockResolvedValue([]) } = {}
) {
  renderWithProviders(tree(), {
    route,
    services: {
      message: {
        getHistory,
        sendText,
        sendAudio: vi.fn(),
        resolveAudioUrl: (url: string) => url,
      },
      createRealtime: () => wire.transport,
    },
  });
}

async function typeAndSend(text: string) {
  await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
  await userEvent.type(screen.getByPlaceholderText('Type your message…'), text);
  await userEvent.click(screen.getByRole('button', { name: 'Send text' }));
}

const terminated = {
  type: 'session_terminated',
  role: 'session_terminated',
  session_id: 'A1B2C3D4',
  reason: 'manual_admin_termination',
  reconnect_allowed: false,
};

const sessionGone = () =>
  new AppError('notFound', { status: 404, serverCode: 'SESSION_NOT_FOUND' });

afterEach(() => {
  vi.useRealTimers();
});

describe('the end of a conversation', () => {
  it('ends the conversation, locks the composer and stops reconnecting', async () => {
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });

    await wire.receive(terminated);

    expect(await screen.findByRole('status')).toHaveTextContent('This conversation has ended.');
    expect(screen.getByRole('button', { name: 'Record' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Open keyboard' })).toBeDisabled();
    expect(wire.transport.disconnect).toHaveBeenCalled();
  });

  it('warns of the time a timeout ends the conversation, and drops the warning then', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(Date.parse('2026-10-12T10:00:00Z'));
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });
    const endsAt = Date.parse('2026-10-12T10:05:00Z');

    await wire.receive({
      type: 'timeout_warning',
      role: 'timeout_warning',
      remaining_minutes: 5,
      timeout_at: '2026-10-12T10:05:00+00:00',
    });

    expect(await screen.findByRole('status')).toHaveTextContent(
      `This conversation will end at ${clockTime(endsAt, 'en')}.`
    );

    await act(async () => {
      vi.advanceTimersByTime(5 * 60_000);
    });

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  // A gateway from before the deadline was sent says only how many minutes.
  it('counts a warning without an end time from when it arrived', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(Date.parse('2026-10-12T10:00:00Z'));
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });

    await wire.receive({ type: 'timeout_warning', role: 'timeout_warning', remaining_minutes: 5 });

    expect(await screen.findByRole('status')).toHaveTextContent(
      clockTime(Date.parse('2026-10-12T10:05:00Z'), 'en')
    );
  });

  // The idle timeout runs only while the admin is away, so their return lifts
  // it. Were it the session's absolute limit instead, the gateway warns again
  // within a minute of the admin connecting.
  it('drops the warning when the admin connects again', async () => {
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });
    await wire.receive({ type: 'timeout_warning', role: 'timeout_warning', remaining_minutes: 5 });
    expect(await screen.findByRole('status')).toBeInTheDocument();

    await wire.receive({ type: 'client_joined', role: 'client_joined', client_type: 'admin' });

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('keeps the warning when it is only the guest who connects again', async () => {
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });
    await wire.receive({ type: 'timeout_warning', role: 'timeout_warning', remaining_minutes: 5 });

    await wire.receive({ type: 'client_joined', role: 'client_joined', client_type: 'customer' });

    expect(screen.getByRole('status')).toHaveTextContent('This conversation will end at');
  });

  it('treats the gateway refusing a send for a session it no longer has as the end', async () => {
    const wire = createRealtimeWire();
    render(wire, { sendText: vi.fn().mockRejectedValue(sessionGone()) });

    await typeAndSend('hello');

    expect(await screen.findByRole('status')).toHaveTextContent('This conversation has ended.');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  // While the gateway is redeployed, the proxy in front of it answers 404.
  it('keeps the conversation open on a 404 the gateway did not send', async () => {
    const wire = createRealtimeWire();
    render(wire, { sendText: vi.fn().mockRejectedValue(new AppError('notFound', { status: 404 })) });

    await typeAndSend('hello');

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText('This conversation has ended.')).not.toBeInTheDocument();
  });

  it('shows no error or retry for a send that fails after the conversation ended', async () => {
    const wire = createRealtimeWire();
    let fail: (error: unknown) => void = () => undefined;
    const sendText = vi.fn().mockReturnValue(
      new Promise((_resolve, reject) => {
        fail = reject;
      })
    );
    render(wire, { sendText });

    await typeAndSend('hello');
    await wire.receive(terminated);
    await act(async () => {
      fail(new AppError('network'));
    });

    expect(screen.getByRole('status')).toHaveTextContent('This conversation has ended.');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  // A guest whose socket was down when the session ended hears nothing over
  // it; the history refetched on reconnecting is where they find out.
  it('ends the conversation when the history refetched on reconnecting is gone', async () => {
    const wire = createRealtimeWire();
    const getHistory = vi.fn().mockResolvedValueOnce([]).mockRejectedValue(sessionGone());
    render(wire, { getHistory });
    await screen.findByRole('button', { name: 'Record' });

    await wire.status('connected');
    await wire.status('disconnected');
    await wire.status('connected');

    expect(await screen.findByText('This conversation has ended.')).toBeInTheDocument();
    expect(wire.transport.disconnect).toHaveBeenCalled();
  });

  it('ends the conversation when its history is already gone on opening it', async () => {
    const wire = createRealtimeWire();
    render(wire, { getHistory: vi.fn().mockRejectedValue(sessionGone()) });

    expect(await screen.findByText('This conversation has ended.')).toBeInTheDocument();
  });
});
