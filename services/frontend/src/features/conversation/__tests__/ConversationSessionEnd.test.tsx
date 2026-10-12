import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { AppError } from '@/core/http/AppError';
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

function render(wire: ReturnType<typeof createRealtimeWire>, sendText = vi.fn()) {
  renderWithProviders(tree(), {
    route,
    services: {
      message: {
        getHistory: vi.fn().mockResolvedValue([]),
        sendText,
        sendAudio: vi.fn(),
        resolveAudioUrl: (url: string) => url,
      },
      createRealtime: () => wire.transport,
    },
  });
}

const terminated = {
  type: 'session_terminated',
  role: 'session_terminated',
  session_id: 'A1B2C3D4',
  reason: 'manual_admin_termination',
  reconnect_allowed: false,
};

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

  it('warns before a timeout and drops the warning once its minutes have passed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const wire = createRealtimeWire();
    render(wire);
    await screen.findByRole('button', { name: 'Record' });

    await wire.receive({ type: 'timeout_warning', role: 'timeout_warning', remaining_minutes: 5 });

    expect(await screen.findByRole('status')).toHaveTextContent(
      'This conversation will end in 5 minutes.'
    );

    await act(async () => {
      vi.advanceTimersByTime(5 * 60_000);
    });

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('treats a send refused as not found as the end, not as something to retry', async () => {
    const wire = createRealtimeWire();
    const sendText = vi.fn().mockRejectedValue(new AppError('notFound', { status: 404 }));
    render(wire, sendText);

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    expect(await screen.findByRole('status')).toHaveTextContent('This conversation has ended.');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });
});
