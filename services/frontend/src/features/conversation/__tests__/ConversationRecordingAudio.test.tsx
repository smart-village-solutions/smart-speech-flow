import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import type { RealtimeEvent, RealtimeTransport } from '@/core/realtime/realtime.port';

interface RecorderConfig {
  maxDurationMs?: number;
  onDataAvailable: (blob: Blob) => void;
  onError: (error: Error) => void;
}

const mocks = vi.hoisted(() => ({
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  capturedConfig: null as RecorderConfig | null,
}));

vi.mock('@/utils/AudioRecorderWithWAVConversion', () => ({
  AudioRecorderWithWAVConversion: class {
    startRecording = mocks.startRecording;
    stopRecording = mocks.stopRecording;
    getStream = () => null;

    constructor(config: RecorderConfig) {
      mocks.capturedConfig = config;
    }
  },
}));

function fakeTransport() {
  const handlers: ((event: RealtimeEvent) => void)[] = [];

  const transport: RealtimeTransport = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    send: vi.fn(),
    onEvent: (handler) => {
      handlers.push(handler);
      return () => handlers.splice(handlers.indexOf(handler), 1);
    },
    onStatus: () => () => undefined,
    getStatus: () => 'connected',
  };

  return {
    transport,
    async receive(event: RealtimeEvent) {
      await act(async () => {
        handlers.forEach((handler) => handler(event));
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

function setup() {
  const player = createFakeAudioPlayer();
  const wire = fakeTransport();

  renderWithProviders(
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>,
    {
      route: '/s/A1B2C3D4/live',
      player: player.port,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn().mockReturnValue(new Promise(() => undefined)),
          resolveAudioUrl: (url: string) => url,
        },
        createRealtime: () => wire.transport,
      },
    }
  );

  return { player, wire };
}

/** Ends the recording the way the recorder does: hand over the audio. */
async function finishRecording() {
  await act(async () => {
    mocks.capturedConfig?.onDataAvailable(new Blob(['wav']));
  });
}

describe('ConversationScreen audio while recording', () => {
  beforeEach(() => {
    mocks.capturedConfig = null;
    mocks.startRecording.mockResolvedValue(undefined);
  });

  it('keeps an arriving message silent while the microphone is open', async () => {
    const { player, wire } = setup();

    await userEvent.click(await screen.findByRole('button', { name: 'Record' }));
    await wire.receive(peerAudioEvent);

    expect(player.played).toEqual([]);
  });

  it('plays what arrived once the recording is handed over', async () => {
    const { player, wire } = setup();

    await userEvent.click(await screen.findByRole('button', { name: 'Record' }));
    await wire.receive(peerAudioEvent);
    await finishRecording();

    expect(player.played).toEqual(['/api/audio/m9.wav']);
  });

  it('silences a clip already playing when recording starts, and replays it after', async () => {
    const { player, wire } = setup();

    await screen.findByRole('button', { name: 'Record' });
    await wire.receive(peerAudioEvent);
    await player.started();
    await player.progress(0.5);

    await userEvent.click(screen.getByRole('button', { name: 'Record' }));

    expect(player.stop).toHaveBeenCalled();

    await finishRecording();

    expect(player.played).toEqual(['/api/audio/m9.wav', '/api/audio/m9.wav']);
  });

  it('resumes playback when the microphone is refused', async () => {
    const { player, wire } = setup();

    await userEvent.click(await screen.findByRole('button', { name: 'Record' }));
    await wire.receive(peerAudioEvent);

    await act(async () => {
      mocks.capturedConfig?.onError(new Error('denied'));
    });

    expect(player.played).toEqual(['/api/audio/m9.wav']);
  });
});
