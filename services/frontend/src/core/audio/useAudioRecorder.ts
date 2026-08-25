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
  const windowRef = useRef<number[]>([]);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
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
    windowRef.current = [];
  }, []);

  const reset = useCallback(() => {
    clearTick();
    closeMeter();
    setPhase('idle');
    setElapsedMs(0);
    setLevels([]);
  }, [clearTick, closeMeter]);

  const start = useCallback(async () => {
    const recorder = new AudioRecorderWithWAVConversion({
      maxDurationMs: maxSeconds * 1000,
      onDataAvailable: (wav) => {
        reset();
        onCompleteRef.current(wav);
      },
      onError: (error) => {
        reset();
        onErrorRef.current(error);
      },
    });

    recorderRef.current = recorder;
    await recorder.startRecording();

    setElapsedMs(0);
    setPhase('recording');

    // The waveform is a nicety: a browser without Web Audio still records.
    try {
      const stream = recorder.getStream();
      meterRef.current = stream === null ? null : createLevelMeter(stream);
    } catch {
      meterRef.current = null;
    }

    setLevels([]);
    windowRef.current = [];

    const ticksPerBar = Math.max(
      1,
      Math.round((maxSeconds * 1000) / BAR_COUNT / TICK_MS)
    );

    tickRef.current = setInterval(() => {
      setElapsedMs((previous) => Math.min(maxSeconds * 1000, previous + TICK_MS));

      const meter = meterRef.current;
      if (meter === null) {
        return;
      }

      windowRef.current.push(meter.read());
      if (windowRef.current.length < ticksPerBar) {
        return;
      }

      const mean =
        windowRef.current.reduce((total, level) => total + level, 0) / windowRef.current.length;
      windowRef.current = [];
      setLevels((previous) =>
        previous.length >= BAR_COUNT ? previous : [...previous, heightFromRms(mean)]
      );
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
