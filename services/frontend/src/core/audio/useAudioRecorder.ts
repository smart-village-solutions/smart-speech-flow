import { useCallback, useEffect, useRef, useState } from 'react';
import { AudioRecorderWithWAVConversion } from '@/utils/AudioRecorderWithWAVConversion';
import { BAR_COUNT, RECORDING_SECONDS } from './waveform';
import { createAnalyserLevelMeter, type LevelMeter } from './level-meter';
import { heightFromRms } from './levels';

export type RecorderPhase = 'idle' | 'recording';

export interface UseAudioRecorderOptions {
  onComplete: (wav: Blob) => void;
  onError: (error: Error) => void;
  maxSeconds?: number;
  /** Injected by tests; the default taps the stream through Web Audio. */
  createLevelMeter?: (stream: MediaStream) => LevelMeter;
}

export interface AudioRecorderState {
  phase: RecorderPhase;
  elapsedSeconds: number;
  /** One bar per committed window, at the loudness actually measured. */
  levels: number[];
  start: () => Promise<void>;
  stop: () => void;
}

/** Ticks at the export's cadence (App.tsx:838): 100ms steps. */
const TICK_MS = 100;

/**
 * Averages the meter across one window and commits a bar when the window is
 * full, so each bar is the loudness actually measured over its slice of time.
 * Returns null while the window is still filling.
 */
function createBarCollector(ticksPerBar: number): (level: number) => number | null {
  let window: number[] = [];

  return (level) => {
    window.push(level);

    if (window.length < ticksPerBar) {
      return null;
    }

    const mean = window.reduce((total, value) => total + value, 0) / window.length;
    window = [];
    return heightFromRms(mean);
  };
}

/**
 * The waveform is a nicety: a browser without Web Audio still records, so
 * neither reaching for the stream nor tapping it may take the recording down.
 */
function openMeter(
  getStream: () => MediaStream | null,
  createLevelMeter: (stream: MediaStream) => LevelMeter
): LevelMeter | null {
  try {
    const stream = getStream();
    return stream === null ? null : createLevelMeter(stream);
  } catch {
    return null;
  }
}

export function useAudioRecorder(options: UseAudioRecorderOptions): AudioRecorderState {
  const {
    onComplete,
    onError,
    maxSeconds = RECORDING_SECONDS,
    createLevelMeter = createAnalyserLevelMeter,
  } = options;

  const [phase, setPhase] = useState<RecorderPhase>('idle');
  const [levels, setLevels] = useState<number[]>([]);
  // Accumulated as integer milliseconds. The export adds 0.1 to a float, which
  // drifts below the true elapsed time and costs the waveform its last bar.
  const [elapsedMs, setElapsedMs] = useState(0);

  const recorderRef = useRef<AudioRecorderWithWAVConversion | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const meterRef = useRef<LevelMeter | null>(null);
  const collectRef = useRef<((level: number) => number | null) | null>(null);
  // Held together in one ref so a new callback identity never restarts a
  // recording in progress; they are always replaced as a pair.
  const handlersRef = useRef({ onComplete, onError });

  useEffect(() => {
    handlersRef.current = { onComplete, onError };
  });

  const clearTick = useCallback(() => {
    if (tickRef.current !== null) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const closeMeter = useCallback(() => {
    meterRef.current?.close();
    meterRef.current = null;
    collectRef.current = null;
  }, []);

  const reset = useCallback(() => {
    clearTick();
    closeMeter();
    setPhase('idle');
    setElapsedMs(0);
    setLevels([]);
  }, [clearTick, closeMeter]);

  const start = useCallback(async () => {
    // startRecording() reports its own failures through onError and resolves
    // regardless, so a refused microphone is invisible to the await below.
    // Without this flag the hook goes on to show a recording that is not
    // happening, and stop() cannot end it — the recorder has already cleaned up.
    let refused = false;

    const recorder = new AudioRecorderWithWAVConversion({
      maxDurationMs: maxSeconds * 1000,
      onDataAvailable: (wav) => {
        reset();
        handlersRef.current.onComplete(wav);
      },
      onError: (error) => {
        refused = true;
        reset();
        handlersRef.current.onError(error);
      },
    });

    recorderRef.current = recorder;
    await recorder.startRecording();

    if (refused) {
      recorderRef.current = null;
      return;
    }

    setElapsedMs(0);
    setPhase('recording');
    setLevels([]);

    meterRef.current = openMeter(() => recorder.getStream(), createLevelMeter);
    collectRef.current = createBarCollector(
      Math.max(1, Math.round((maxSeconds * 1000) / BAR_COUNT / TICK_MS))
    );

    tickRef.current = setInterval(() => {
      setElapsedMs((previous) => Math.min(maxSeconds * 1000, previous + TICK_MS));

      const level = meterRef.current?.read();
      const bar = level === undefined ? null : collectRef.current?.(level);

      if (bar === null || bar === undefined) {
        return;
      }

      setLevels((previous) => (previous.length >= BAR_COUNT ? previous : [...previous, bar]));
    }, TICK_MS);
  }, [createLevelMeter, maxSeconds, reset]);

  const stop = useCallback(() => {
    clearTick();
    recorderRef.current?.stopRecording();
  }, [clearTick]);

  useEffect(() => {
    return () => {
      clearTick();
      closeMeter();
    };
  }, [clearTick, closeMeter]);

  return {
    phase,
    elapsedSeconds: elapsedMs / 1000,
    levels,
    start,
    stop,
  };
}
