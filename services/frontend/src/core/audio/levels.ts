/**
 * Turning real audio into bar heights, for both halves of the waveform: live
 * microphone level while recording, and a decoded clip's envelope on playback.
 */

/** Silence still gets a hairline, so the bar row never looks broken. */
export const MIN_BAR_HEIGHT = 0.08;

/** Maps a quiet speaking voice onto roughly half height. */
const LOUDNESS_GAIN = 1.8;

export function rms(samples: Float32Array): number {
  if (samples.length === 0) {
    return 0;
  }

  let total = 0;
  for (const sample of samples) {
    total += sample * sample;
  }

  return Math.sqrt(total / samples.length);
}

/**
 * Live levels cannot be normalised — the loudest moment has not happened yet —
 * so recording uses a fixed curve. The square root keeps quiet speech visible
 * without letting a shout flatten everything else against the ceiling.
 */
export function heightFromRms(level: number): number {
  return clamp(Math.sqrt(Math.max(0, level)) * LOUDNESS_GAIN);
}

/**
 * A whole clip's envelope, normalised so its loudest moment reaches full
 * height. Without that a quietly recorded message would draw as a flat line.
 */
export function peaksFromSamples(samples: Float32Array, buckets: number): number[] {
  if (buckets <= 0) {
    return [];
  }

  const width = Math.max(1, Math.ceil(samples.length / buckets));
  const levels = Array.from({ length: buckets }, (_, index) =>
    rms(samples.subarray(index * width, (index + 1) * width))
  );

  const loudest = Math.max(...levels);
  if (loudest === 0) {
    return levels.map(() => MIN_BAR_HEIGHT);
  }

  return levels.map((level) => clamp(level / loudest));
}

function clamp(height: number): number {
  return Math.min(1, Math.max(MIN_BAR_HEIGHT, height));
}
