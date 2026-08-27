import { rms } from './levels';

/** Reads the microphone's current loudness, sampled by whoever owns the clock. */
export interface LevelMeter {
  /** Current RMS of the input, 0 to 1. */
  read: () => number;
  close: () => void;
}

/**
 * Taps the recording stream through an AnalyserNode. Nothing is connected to
 * the context destination, so listening in costs no echo.
 */
export function createAnalyserLevelMeter(stream: MediaStream): LevelMeter {
  const browser = globalThis as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const Constructor = browser.AudioContext ?? browser.webkitAudioContext;
  if (!Constructor) {
    throw new Error('Web Audio is unavailable');
  }

  const context = new Constructor();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);

  const window = new Float32Array(analyser.fftSize);

  return {
    read() {
      analyser.getFloatTimeDomainData(window);
      return rms(window);
    },
    close() {
      source.disconnect();
      void context.close();
    },
  };
}
