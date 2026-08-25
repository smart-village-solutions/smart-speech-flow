import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { FLIGHT_MS } from '@/features/conversation/useSendFlight';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import type {
  RealtimeEvent,
  RealtimeStatus,
  RealtimeTransport,
} from '@/core/realtime/realtime.port';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import type { SendResult } from '@/domain/message/message.types';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>
  );
}

const route = '/s/A1B2C3D4/live';

/** A transport the test pushes gateway events through by hand. */
function fakeTransport() {
  const handlers: ((event: RealtimeEvent) => void)[] = [];
  const statusHandlers: ((status: RealtimeStatus) => void)[] = [];

  const transport: RealtimeTransport = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    send: vi.fn(),
    onEvent: (handler) => {
      handlers.push(handler);
      return () => handlers.splice(handlers.indexOf(handler), 1);
    },
    onStatus: (handler) => {
      statusHandlers.push(handler);
      return () => statusHandlers.splice(statusHandlers.indexOf(handler), 1);
    },
    getStatus: () => 'connected',
  };

  return {
    transport,
    async receive(event: RealtimeEvent) {
      await act(async () => {
        handlers.forEach((handler) => handler(event));
      });
    },
    async status(next: RealtimeStatus) {
      await act(async () => {
        statusHandlers.forEach((handler) => handler(next));
      });
    },
  };
}

const peerAudioEvent = {
  role: 'receiver_message',
  message_id: 'm9',
  text: 'Guten Tag',
  source_lang: 'de',
  target_lang: 'en',
  audio_url: '/api/audio/m9.wav',
  timestamp: '2026-08-24T10:00:00+00:00',
};

describe('ConversationScreen', () => {
  it('offers the record and keyboard controls', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByRole('button', { name: 'Record' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open keyboard' })).toBeInTheDocument();
  });

  it('opens the composer and disables send until text is typed', async () => {
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));

    const composer = screen.getByPlaceholderText('Type your message…');
    expect(composer).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send text' })).toBeDisabled();

    await userEvent.type(composer, 'hello');

    expect(screen.getByRole('button', { name: 'Send text' })).toBeEnabled();
  });

  it('sends the typed message and shows it as a bubble', async () => {
    const sendText = vi.fn().mockResolvedValue({
      messageId: 'm5',
      originalText: 'hello',
      translatedText: 'hallo',
      audioUrl: null,
      processingTimeMs: 100,
    });

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText,
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    expect(sendText).toHaveBeenCalledWith('A1B2C3D4', expect.objectContaining({ text: 'hello' }));
    expect(await screen.findByText('hello')).toBeInTheDocument();
  });

  it('turns the composer box into a dots box that flies to the stack on send', async () => {
    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          // Left in flight, as a real send would be.
          sendText: vi.fn().mockReturnValue(new Promise(() => undefined)),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    // The composer is replaced in place by a dots box carrying the flight, not
    // cut away: two sets of dots are on screen, the flying one and the bubble
    // it is heading for.
    expect(screen.queryByPlaceholderText('Type your message…')).not.toBeInTheDocument();
    const flying = document.querySelector('.send-flight');
    expect(flying).not.toBeNull();
    expect(flying?.querySelector('[data-testid="typing-dots"]')).not.toBeNull();
    expect(screen.getAllByTestId('typing-dots').length).toBe(2);

    await waitFor(
      () => {
        expect(document.querySelector('.send-flight')).toBeNull();
      },
      { timeout: FLIGHT_MS * 2 }
    );
  });

  it('offers a retry when a send fails', async () => {
    const sendText = vi.fn().mockRejectedValue(new Error('boom'));

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText,
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('That message could not be sent.');

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(sendText).toHaveBeenCalledTimes(2);
  });

  it('plays an incoming message as soon as it arrives', async () => {
    const player = createFakeAudioPlayer();
    const wire = fakeTransport();

    renderWithProviders(tree(), {
      route,
      player: player.port,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await screen.findByRole('button', { name: 'Record' });
    await wire.receive(peerAudioEvent);

    expect(player.played).toEqual(['/api/audio/m9.wav']);
  });

  it('stays silent when history loads, however much audio it holds', async () => {
    const player = createFakeAudioPlayer();

    renderWithProviders(tree(), {
      route,
      player: player.port,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([
            {
              id: 'old1',
              origin: 'peer',
              text: 'Guten Tag',
              audioUrl: '/api/audio/old1.wav',
              sourceLanguage: 'de',
              targetLanguage: 'en',
              timestamp: '2026-08-24T09:00:00+00:00',
              state: 'sent',
            },
          ]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
      },
    });

    expect(await screen.findByText('Guten Tag')).toBeInTheDocument();
    expect(player.played).toEqual([]);
  });

  it('never autoplays the customer\'s own confirmed message', async () => {
    const player = createFakeAudioPlayer();
    const wire = fakeTransport();

    renderWithProviders(tree(), {
      route,
      player: player.port,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await screen.findByRole('button', { name: 'Record' });
    await wire.receive({ ...peerAudioEvent, role: 'sender_confirmation' });

    expect(player.played).toEqual([]);
  });

  it('queues a burst of arrivals and plays them in order', async () => {
    const player = createFakeAudioPlayer();
    const wire = fakeTransport();

    renderWithProviders(tree(), {
      route,
      player: player.port,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await screen.findByRole('button', { name: 'Record' });
    await wire.receive(peerAudioEvent);
    await player.started();
    await wire.receive({ ...peerAudioEvent, message_id: 'm10', audio_url: '/api/audio/m10.wav' });

    expect(player.played).toEqual(['/api/audio/m9.wav']);

    await player.end();

    expect(player.played).toEqual(['/api/audio/m9.wav', '/api/audio/m10.wav']);
  });

  it('falls silent when the customer leaves the conversation', async () => {
    const player = createFakeAudioPlayer();
    const wire = fakeTransport();

    // Both routes under one provider, so leaving unmounts the screen but not
    // the player — exactly what happens in the app.
    renderWithProviders(
      <Routes>
        <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
        <Route path="/" element={<p>home</p>} />
      </Routes>,
      {
        route,
        player: player.port,
        services: {
          message: {
            getHistory: vi.fn().mockResolvedValue([]),
            sendText: vi.fn(),
            sendAudio: vi.fn(),
            audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
          },
          createRealtime: () => wire.transport,
        },
      }
    );

    await screen.findByRole('button', { name: 'Record' });
    await wire.receive(peerAudioEvent);
    await player.started();
    expect(player.stop).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Home' }));

    expect(await screen.findByText('home')).toBeInTheDocument();
    expect(player.stop).toHaveBeenCalled();
  });

  it('recovers a message the gateway broadcast while the socket was down', async () => {
    const wire = fakeTransport();
    const missed = {
      id: 'm42',
      origin: 'peer' as const,
      text: 'the message that went missing',
      audioUrl: null,
      sourceLanguage: 'de',
      targetLanguage: 'en',
      timestamp: '2026-08-24T10:32:40+00:00',
      state: 'sent' as const,
    };
    const getHistory = vi.fn().mockResolvedValueOnce([]).mockResolvedValueOnce([missed]);

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory,
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await screen.findByRole('button', { name: 'Record' });
    expect(screen.queryByText('the message that went missing')).not.toBeInTheDocument();

    // The heartbeat kill and the reconnect that follows it.
    await wire.status('connected');
    await wire.status('disconnected');
    await wire.status('connected');

    expect(await screen.findByText('the message that went missing')).toBeInTheDocument();
  });

  it('does not refetch on the first connect', async () => {
    const wire = fakeTransport();
    const getHistory = vi.fn().mockResolvedValue([]);

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory,
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await screen.findByRole('button', { name: 'Record' });
    await wire.status('connected');

    expect(getHistory).toHaveBeenCalledTimes(1);
  });

  it('shows one bubble when the socket confirmation overtakes the send response', async () => {
    const wire = fakeTransport();
    let settle: ((result: SendResult) => void) | null = null;
    const sendText = vi.fn(
      () =>
        new Promise<SendResult>((resolve) => {
          settle = resolve;
        })
    );

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText,
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
        createRealtime: () => wire.transport,
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    // The gateway broadcasts before it answers the request, so the socket
    // confirmation can land first.
    await wire.receive({
      role: 'sender_confirmation',
      message_id: 'm7',
      text: 'hello',
      source_lang: 'en',
      target_lang: 'de',
      timestamp: '2026-08-24T10:00:00+00:00',
    });

    await act(async () => {
      settle?.({
        messageId: 'm7',
        originalText: 'hello',
        translatedText: 'hallo',
        audioUrl: null,
        processingTimeMs: 100,
      });
    });

    expect(await screen.findAllByText('hello')).toHaveLength(1);
  });
});
