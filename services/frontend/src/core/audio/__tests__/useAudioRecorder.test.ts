import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioRecorder } from '@/core/audio/useAudioRecorder';

interface RecorderConfig {
  maxDurationMs?: number;
  onDataAvailable: (blob: Blob) => void;
  onError: (error: Error) => void;
}

const mocks = vi.hoisted(() => ({
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  getStream: vi.fn(() => ({}) as MediaStream),
  capturedConfig: null as RecorderConfig | null,
}));

vi.mock('@/utils/AudioRecorderWithWAVConversion', () => ({
  AudioRecorderWithWAVConversion: class {
    startRecording = mocks.startRecording;
    stopRecording = mocks.stopRecording;
    getStream = mocks.getStream;

    constructor(config: RecorderConfig) {
      mocks.capturedConfig = config;
    }
  },
}));

function config(): RecorderConfig {
  if (mocks.capturedConfig === null) {
    throw new Error('the recorder was never constructed');
  }
  return mocks.capturedConfig;
}

beforeEach(() => {
  mocks.capturedConfig = null;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAudioRecorder', () => {
  it('starts idle with no elapsed time', () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onComplete: vi.fn(), onError: vi.fn() })
    );

    expect(result.current.phase).toBe('idle');
    expect(result.current.elapsedSeconds).toBe(0);
    expect(result.current.levels).toEqual([]);
  });

  it('enters the recording phase and advances elapsed time', async () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.phase).toBe('recording');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.elapsedSeconds).toBeCloseTo(1, 1);
  });

  it('caps elapsed time at the recording limit', async () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(result.current.elapsedSeconds).toBe(20);
  });

  it('returns to idle and reports the WAV blob when recording completes', async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useAudioRecorder({ onComplete, onError: vi.fn() }));

    await act(async () => {
      await result.current.start();
    });

    const blob = new Blob(['wav'], { type: 'audio/wav' });
    act(() => {
      config().onDataAvailable(blob);
    });

    expect(onComplete).toHaveBeenCalledWith(blob);
    expect(result.current.phase).toBe('idle');
    expect(result.current.elapsedSeconds).toBe(0);
  });

  it('returns to idle and reports errors', async () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useAudioRecorder({ onComplete: vi.fn(), onError }));

    await act(async () => {
      await result.current.start();
    });

    const failure = new Error('microphone blocked');
    act(() => {
      config().onError(failure);
    });

    expect(onError).toHaveBeenCalledWith(failure);
    expect(result.current.phase).toBe('idle');
  });

  it('passes the recording limit to the underlying recorder', async () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => {
      await result.current.start();
    });

    expect(config().maxDurationMs).toBe(20_000);
  });

  it('stops the underlying recorder on request', async () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.stop();
    });

    expect(mocks.stopRecording).toHaveBeenCalled();
  });

  describe('live input levels', () => {
    /** A meter the test drives; one reading per 100ms tick. */
    function meter(readings: number[]) {
      let index = 0;
      const close = vi.fn();
      return {
        close,
        create: vi.fn(() => ({
          read: () => readings[Math.min(index++, readings.length - 1)] ?? 0,
          close,
        })),
      };
    }

    it('starts with no bars at all', async () => {
      const fake = meter([0.2]);
      const { result } = renderHook(() =>
        useAudioRecorder({
          onComplete: vi.fn(),
          onError: vi.fn(),
          createLevelMeter: fake.create,
        })
      );

      await act(async () => {
        await result.current.start();
      });

      expect(result.current.levels).toEqual([]);
    });

    it('commits one bar per 400ms of speech, at the loudness measured', async () => {
      // 20s over 50 bars is 400ms a bar, and the recorder ticks every 100ms.
      const fake = meter([0.09, 0.09, 0.09, 0.09, 0.36, 0.36, 0.36, 0.36]);
      const { result } = renderHook(() =>
        useAudioRecorder({
          onComplete: vi.fn(),
          onError: vi.fn(),
          createLevelMeter: fake.create,
        })
      );

      await act(async () => {
        await result.current.start();
      });

      await act(async () => {
        vi.advanceTimersByTime(400);
      });
      expect(result.current.levels).toHaveLength(1);

      await act(async () => {
        vi.advanceTimersByTime(400);
      });
      expect(result.current.levels).toHaveLength(2);

      // Louder speech draws a taller bar.
      expect(result.current.levels[1]).toBeGreaterThan(result.current.levels[0]);
    });

    it('closes the meter and clears the bars when recording ends', async () => {
      const fake = meter([0.2]);
      const onComplete = vi.fn();
      const { result } = renderHook(() =>
        useAudioRecorder({ onComplete, onError: vi.fn(), createLevelMeter: fake.create })
      );

      await act(async () => {
        await result.current.start();
      });
      await act(async () => {
        vi.advanceTimersByTime(400);
      });
      expect(result.current.levels).toHaveLength(1);

      await act(async () => {
        config().onDataAvailable(new Blob(['wav']));
      });

      expect(fake.close).toHaveBeenCalled();
      expect(result.current.levels).toEqual([]);
    });

    it('records without a waveform when the meter cannot be built', async () => {
      const onError = vi.fn();
      const { result } = renderHook(() =>
        useAudioRecorder({
          onComplete: vi.fn(),
          onError,
          createLevelMeter: () => {
            throw new Error('Web Audio is unavailable');
          },
        })
      );

      await act(async () => {
        await result.current.start();
      });
      await act(async () => {
        vi.advanceTimersByTime(400);
      });

      expect(result.current.phase).toBe('recording');
      expect(result.current.levels).toEqual([]);
      expect(onError).not.toHaveBeenCalled();
    });
  });
});
