import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppError } from '@/core/http/AppError';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import type { RealtimeTransport } from '@/core/realtime/realtime.port';

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

const transport: RealtimeTransport = {
  connect: vi.fn().mockResolvedValue(undefined),
  disconnect: vi.fn(),
  send: vi.fn(),
  onEvent: () => () => undefined,
  onStatus: () => () => undefined,
  getStatus: () => 'connected',
};

describe('ConversationScreen when a recording held no speech', () => {
  beforeEach(() => {
    mocks.capturedConfig = null;
    mocks.startRecording.mockResolvedValue(undefined);
  });

  it('tells the speaker that nothing was recognised', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
      </Routes>,
      {
        route: '/s/A1B2C3D4/live',
        services: {
          message: {
            getHistory: vi.fn().mockResolvedValue([]),
            sendText: vi.fn(),
            sendAudio: vi.fn().mockRejectedValue(new AppError('noSpeech', { status: 422 })),
            resolveAudioUrl: (url: string) => url,
          },
          createRealtime: () => transport,
        },
      }
    );

    await userEvent.click(await screen.findByRole('button', { name: 'Record' }));
    act(() => {
      mocks.capturedConfig?.onDataAvailable(new Blob(['wav']));
    });

    expect(
      await screen.findByText('Nothing was recognised. Please try again.')
    ).toBeInTheDocument();
  });
});
